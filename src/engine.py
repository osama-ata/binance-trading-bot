"""Event-driven trading engine: one evaluation per *closed* candle per symbol, fed by Binance websocket streams."""
import logging
import math
from datetime import timedelta

import pandas as pd

from binance_client import BinanceClient, interval_to_timedelta
from brokers import Broker
from data import load_klines
from risk import RiskManager, updated_stop
from strategies import BaseStrategy

log = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, client: BinanceClient, broker: Broker, strategy: BaseStrategy, risk: RiskManager,
                 symbols: list[str], interval: str, warmup_bars: int | None = None):
        self.client = client
        self.broker = broker
        self.strategy = strategy
        self.risk = risk
        self.symbols = symbols
        self.interval = interval
        self.bar = interval_to_timedelta(interval)
        self.keep_bars = max(warmup_bars or 0, strategy.warmup_bars(self.bar)) + 50
        self.frames: dict[str, pd.DataFrame] = {}
        self.prices: dict[str, float] = {}
        self._last_risk_bar: pd.Timestamp | None = None

    def warmup(self) -> None:
        days = math.ceil(self.keep_bars * self.bar / timedelta(days=1)) + 1
        start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).date()
        for sym in self.symbols:
            df = load_klines(sym, self.interval, start, client=self.client)
            self.frames[sym] = df.iloc[-self.keep_bars:]
            self.prices[sym] = float(df["Close"].iloc[-1])
            log.info("warmup %s: %d bars up to %s", sym, len(df), df.index[-1])
        for sym, pos in self.broker.positions.items():
            log.info("resuming open position %s qty=%s entry=%.2f stop=%.2f", sym, pos.qty, pos.entry, pos.stop)

    async def on_update(self, symbol: str, bar: dict) -> None:
        self.prices[symbol] = bar["Close"]

    async def on_bar(self, symbol: str, t: pd.Timestamp, bar: dict) -> None:
        try:
            self._process_bar(symbol, t, bar)
        except Exception:
            log.exception("error processing %s bar %s", symbol, t)

    def _process_bar(self, symbol: str, t: pd.Timestamp, bar: dict) -> None:
        df = self.frames[symbol]
        df.loc[t] = [bar[c] for c in df.columns]
        self.frames[symbol] = df = df.iloc[-self.keep_bars:]
        self.prices[symbol] = bar["Close"]
        now = (t + self.bar).to_pydatetime()  # bar close time

        if self._last_risk_bar != t:  # once per bar across all symbols
            self._last_risk_bar = t
            self.risk.on_bar(now, self.broker.equity(self.prices))

        ind = self.strategy.prepare(df)
        i = len(ind) - 1

        # 1) exits: stop / target fills, then break-even, time stop, discretionary exit
        pnl = self.broker.check_exits(symbol, bar, now)
        if pnl is not None:
            self.risk.on_close(pnl)
        pos = self.broker.positions.get(symbol)
        if pos:
            pos.bars_held += 1
            new_stop = updated_stop(pos, bar["High"], self.strategy.p["breakeven_at_r"])
            if new_stop != pos.stop:
                self.broker.move_stop(symbol, new_stop)
            reason = "time stop" if pos.bars_held >= self.strategy.p["max_bars"] else self.strategy.exit_signal(ind, i)
            if reason:
                self.risk.on_close(self.broker.close(symbol, bar["Close"], reason, now))
            else:
                self.broker.store.updated(pos)

        # 2) entries
        elif (sig := self.strategy.entry_signal(ind, i)) is not None:
            ok, why = self.risk.can_open(len(self.broker.positions))
            if not ok:
                log.info("%s signal skipped: %s", symbol, why)
            else:
                equity = self.broker.equity(self.prices)
                qty = self.risk.size(equity, sig.entry, sig.stop)
                if self.broker.open(symbol, qty, sig, self.strategy.name, now):
                    self.risk.on_open()
                    log.info("%s ENTRY %s qty=%.6f stop=%.2f target=%.2f", symbol, sig.reason, qty, sig.stop, sig.target)

        equity = self.broker.equity(self.prices)
        self.broker.store.snapshot(equity, self.broker.cash(), now)
        log.info("%s close=%.2f equity=%.2f open=%s%s", symbol, bar["Close"], equity, list(self.broker.positions),
                 " HALTED" if self.risk.halted else "")

    async def run(self) -> None:
        self.warmup()
        await self.client.stream_closed_klines(self.symbols, self.interval, self.on_bar, self.on_update)
