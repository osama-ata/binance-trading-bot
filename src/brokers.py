"""Order execution: a paper broker for VIRTUAL mode and a Binance broker for LIVE mode.

Both expose the same interface and both persist positions through `Store`, so a restart resumes open trades.
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from binance_client import BinanceClient
from database import EquitySnapshot, PositionRow, Trade, session_scope
from risk import Position, bar_exit
from strategies import Signal

log = logging.getLogger(__name__)


class Store:
    """DB persistence. Pass factory=None to run without a database (tests, quick experiments)."""

    def __init__(self, factory: sessionmaker[Session] | None, mode: str):
        self.factory = factory
        self.mode = mode

    def load_open_positions(self) -> dict[str, Position]:
        if not self.factory:
            return {}
        with session_scope(self.factory) as s:
            rows = s.query(PositionRow).filter_by(mode=self.mode, status="OPEN").all()
            return {
                r.symbol: Position(
                    symbol=r.symbol, qty=r.qty, entry=r.entry_price, stop=r.stop, target=r.target,
                    initial_stop=r.initial_stop, opened_at=r.opened_at, strategy=r.strategy,
                    reason=r.entry_reason or "", bars_held=r.bars_held or 0, fee_paid=r.entry_fee or 0.0,
                    exit_order_list_id=r.exit_order_list_id, db_id=r.id,
                )
                for r in rows
            }

    def last_cash(self) -> float | None:
        if not self.factory:
            return None
        with session_scope(self.factory) as s:
            row = s.query(EquitySnapshot).filter_by(mode=self.mode).order_by(EquitySnapshot.id.desc()).first()
            return row.cash if row else None

    def opened(self, pos: Position, order_id: str) -> None:
        if not self.factory:
            return
        with session_scope(self.factory) as s:
            row = PositionRow(
                symbol=pos.symbol, mode=self.mode, strategy=pos.strategy, qty=pos.qty, entry_price=pos.entry,
                stop=pos.stop, initial_stop=pos.initial_stop, target=pos.target, opened_at=pos.opened_at,
                entry_fee=pos.fee_paid, exit_order_list_id=pos.exit_order_list_id, entry_reason=pos.reason,
            )
            s.add(row)
            s.flush()
            pos.db_id = row.id
            s.add(Trade(
                symbol=pos.symbol, side="BUY", price=pos.entry, quantity=pos.qty, timestamp=pos.opened_at,
                order_id=order_id, strategy=pos.strategy, mode=self.mode, fee=pos.fee_paid, reason=pos.reason,
                position_id=row.id,
            ))

    def updated(self, pos: Position) -> None:
        if not self.factory or pos.db_id is None:
            return
        with session_scope(self.factory) as s:
            row = s.get(PositionRow, pos.db_id)
            row.stop, row.bars_held, row.exit_order_list_id = pos.stop, pos.bars_held, pos.exit_order_list_id

    def closed(self, pos: Position, price: float, fee: float, pnl: float, reason: str, order_id: str, now: datetime):
        if not self.factory:
            return
        with session_scope(self.factory) as s:
            if pos.db_id is not None:
                row = s.get(PositionRow, pos.db_id)
                row.status, row.closed_at, row.exit_price = "CLOSED", now, price
                row.exit_reason, row.pnl, row.bars_held = reason, pnl, pos.bars_held
            s.add(Trade(
                symbol=pos.symbol, side="SELL", price=price, quantity=pos.qty, timestamp=now, order_id=order_id,
                strategy=pos.strategy, mode=self.mode, fee=fee, pnl=pnl, reason=reason, position_id=pos.db_id,
            ))

    def snapshot(self, equity: float, cash: float, now: datetime) -> None:
        if not self.factory:
            return
        with session_scope(self.factory) as s:
            s.add(EquitySnapshot(timestamp=now, mode=self.mode, equity=equity, cash=cash))


class Broker:
    def __init__(self, store: Store):
        self.store = store
        self.positions: dict[str, Position] = store.load_open_positions()

    def cash(self) -> float:
        raise NotImplementedError

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash() + sum(p.qty * prices.get(s, p.entry) for s, p in self.positions.items())

    def open(self, symbol: str, qty: float, sig: Signal, strategy: str, now: datetime) -> Position | None:
        raise NotImplementedError

    def close(self, symbol: str, price_hint: float, reason: str, now: datetime) -> float:
        raise NotImplementedError

    def check_exits(self, symbol: str, bar: dict, now: datetime) -> float | None:
        """Process stop/target fills for this closed bar. Returns realised PnL if the position closed."""
        raise NotImplementedError

    def move_stop(self, symbol: str, new_stop: float) -> None:
        pos = self.positions[symbol]
        pos.stop = new_stop
        self.store.updated(pos)


class PaperBroker(Broker):
    """Simulated fills: market orders pay the spread (book ticker, if a client is given) plus slippage plus fee;
    targets fill as resting maker limits; stops fill at the stop (or the bar open if it gapped through)."""

    def __init__(self, store: Store, cash: float, fee_rate: float = 0.001, slippage_bps: float = 2.0,
                 client: BinanceClient | None = None):
        super().__init__(store)
        restored = store.last_cash()
        self._cash = restored if restored is not None else cash
        self.fee_rate = fee_rate
        self.slip = slippage_bps / 1e4
        self.client = client

    def cash(self) -> float:
        return self._cash

    def _quote(self, symbol: str, side: str, ref: float) -> float:
        price = ref
        if self.client:
            try:
                bid, ask = self.client.get_book_ticker(symbol)
                price = ask if side == "BUY" else bid
            except Exception as e:  # fall back to the bar close
                log.warning("book ticker failed for %s: %s", symbol, e)
        return price * (1 + self.slip) if side == "BUY" else price * (1 - self.slip)

    def open(self, symbol, qty, sig, strategy, now):
        price = self._quote(symbol, "BUY", sig.entry)
        fee = qty * price * self.fee_rate
        if qty <= 0 or qty * price + fee > self._cash:
            log.info("paper: insufficient cash for %s", symbol)
            return None
        self._cash -= qty * price + fee
        pos = Position(symbol=symbol, qty=qty, entry=price, stop=sig.stop, target=sig.target,
                       initial_stop=sig.stop, opened_at=now, strategy=strategy, reason=sig.reason, fee_paid=fee)
        self.positions[symbol] = pos
        self.store.opened(pos, order_id="paper")
        return pos

    def _settle(self, symbol: str, price: float, reason: str, now: datetime) -> float:
        pos = self.positions.pop(symbol)
        fee = pos.qty * price * self.fee_rate
        self._cash += pos.qty * price - fee
        pnl = pos.qty * (price - pos.entry) - pos.fee_paid - fee
        self.store.closed(pos, price, fee, pnl, reason, "paper", now)
        return pnl

    def close(self, symbol, price_hint, reason, now):
        return self._settle(symbol, self._quote(symbol, "SELL", price_hint), reason, now)

    def check_exits(self, symbol, bar, now):
        pos = self.positions.get(symbol)
        if not pos:
            return None
        hit = bar_exit(pos, bar["High"], bar["Low"])
        if not hit:
            return None
        reason, level = hit
        price = min(level, bar["Open"]) * (1 - self.slip) if reason == "stop" else level
        return self._settle(symbol, price, reason, now)


class BinanceBroker(Broker):
    """Real orders: market entry, then an exchange-side OCO (LIMIT_MAKER target + STOP_LOSS) so the position
    stays protected even if the bot dies. All symbols are assumed to share one quote asset (e.g. USDT)."""

    def __init__(self, store: Store, client: BinanceClient, quote_asset: str = "USDT", fee_rate: float = 0.001):
        super().__init__(store)
        self.client = client
        self.quote_asset = quote_asset
        self.fee_rate = fee_rate

    def cash(self) -> float:
        return self.client.get_free_balance(self.quote_asset)

    def _fee_in_quote(self, fill: dict, base_asset: str) -> float:
        if fill["fee_asset"] == self.quote_asset:
            return fill["fee"]
        if fill["fee_asset"] == base_asset:
            return fill["fee"] * fill["avg_price"]
        return fill["qty"] * fill["avg_price"] * self.fee_rate  # e.g. paid in BNB: estimate

    def open(self, symbol, qty, sig, strategy, now):
        f = self.client.exchange_filters(symbol)
        qty = f.round_qty(qty)
        if not f.is_tradeable(qty, sig.entry):
            log.info("%s: qty %s below exchange minimums", symbol, qty)
            return None
        fill = self.client.market_buy(symbol, qty)
        if fill["qty"] <= 0:
            log.error("%s: market buy not filled: %s", symbol, fill)
            return None
        # If the fee was taken in the base asset we hold less than we bought
        held = fill["qty"] - (fill["fee"] if fill["fee_asset"] == f.base_asset else 0.0)
        held = f.round_qty(held)
        pos = Position(symbol=symbol, qty=held, entry=fill["avg_price"], stop=sig.stop, target=sig.target,
                       initial_stop=sig.stop, opened_at=now, strategy=strategy, reason=sig.reason,
                       fee_paid=self._fee_in_quote(fill, f.base_asset))
        try:
            pos.exit_order_list_id = self.client.place_exit_oco(symbol, held, pos.target, pos.stop)
        except Exception:
            log.exception("%s: failed to place protective OCO, flattening position", symbol)
            self.client.market_sell(symbol, held)
            return None
        self.positions[symbol] = pos
        self.store.opened(pos, order_id=fill["order_id"])
        log.info("LIVE BUY %s %s @ %.2f (stop %.2f, target %.2f)", symbol, held, pos.entry, pos.stop, pos.target)
        return pos

    def _finish(self, pos: Position, price: float, fee: float, reason: str, order_id: str, now: datetime) -> float:
        self.positions.pop(pos.symbol, None)
        pnl = pos.qty * (price - pos.entry) - pos.fee_paid - fee
        self.store.closed(pos, price, fee, pnl, reason, order_id, now)
        log.info("LIVE EXIT %s @ %.2f (%s) pnl %.2f", pos.symbol, price, reason, pnl)
        return pnl

    def close(self, symbol, price_hint, reason, now):
        pos = self.positions[symbol]
        if pos.exit_order_list_id is not None:
            self.client.cancel_order_list(symbol, pos.exit_order_list_id)
        fill = self.client.market_sell(symbol, pos.qty)
        f = self.client.exchange_filters(symbol)
        return self._finish(pos, fill["avg_price"], self._fee_in_quote(fill, f.base_asset), reason, fill["order_id"], now)

    def check_exits(self, symbol, bar, now):
        pos = self.positions.get(symbol)
        if not pos or pos.exit_order_list_id is None:
            return None
        status = self.client.get_order_list_status(pos.exit_order_list_id)
        if status.get("listOrderStatus") != "ALL_DONE":
            return None
        for o in status.get("orders", []):
            order = self.client.get_order(symbol, o["orderId"])
            if order["status"] == "FILLED" and float(order["executedQty"]) > 0:
                price = float(order["cummulativeQuoteQty"]) / float(order["executedQty"])
                reason = "target" if order["type"] == "LIMIT_MAKER" else "stop"
                fee = float(order["cummulativeQuoteQty"]) * self.fee_rate  # estimate; exact fees are in myTrades
                return self._finish(pos, price, fee, reason, str(order["orderId"]), now)
        # Done but nothing filled => cancelled externally (e.g. manually on the website)
        log.warning("%s: exit OCO was cancelled outside the bot; no longer managing this position", symbol)
        self.positions.pop(symbol, None)
        self.store.closed(pos, bar["Close"], 0.0, pos.qty * (bar["Close"] - pos.entry) - pos.fee_paid,
                          "external", "", now)
        return None

    def move_stop(self, symbol, new_stop):
        pos = self.positions[symbol]
        if pos.exit_order_list_id is not None:
            self.client.cancel_order_list(symbol, pos.exit_order_list_id)
        pos.stop = new_stop
        pos.exit_order_list_id = self.client.place_exit_oco(symbol, pos.qty, pos.target, pos.stop)
        self.store.updated(pos)
