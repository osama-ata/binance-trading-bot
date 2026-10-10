"""Backtesting for any BaseStrategy via backtesting.py, with the same risk rules as the live engine.

Execution model: signals are computed on a closed bar and filled at the next bar's open
(backtesting.py default, matches the live engine placing a market order right after candle close).
Costs: `commission` per side (Binance spot 0.1%) plus `spread` (models slippage/half-spread both ways).
"""
import warnings
from dataclasses import dataclass
from typing import Any

from multiprocessing.dummy import Pool as ThreadPool

import backtesting
import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import FractionalBacktest

from risk import RiskManager
from strategies import STRATEGIES, BaseStrategy

FRACTIONAL_UNIT = 1e-8  # trade in satoshi-sized units so crypto position sizes aren't rounded to whole coins

# Run optimiser jobs on threads: same speed here as processes, and avoids Python 3.11's noisy
# shared-memory resource_tracker errors on macOS.
backtesting.Pool = lambda processes=None, initializer=None, initargs=(): ThreadPool(processes, initializer, initargs)


class _Adapter(Strategy):
    """Wraps a BaseStrategy. Strategy params are injected as class attributes so bt.optimize() can vary them."""

    strategy_cls: type[BaseStrategy] = BaseStrategy
    source_df: pd.DataFrame = pd.DataFrame()
    risk_kwargs: dict[str, Any] = {}
    trade_from: pd.Timestamp | None = None  # walk-forward: ignore signals before this time (indicator warmup)

    def init(self):
        names = {**BaseStrategy.defaults, **self.strategy_cls.defaults}
        self.strat = self.strategy_cls(**{k: getattr(self, k) for k in names if hasattr(self, k)})
        self.ind = self.strat.prepare(self.source_df)
        self.risk = RiskManager(**self.risk_kwargs)
        self._closed_seen = 0

    def next(self):
        i = len(self.data) - 1
        now = self.data.index[-1]
        self.risk.on_bar(now.to_pydatetime(), self.equity)

        for t in self.closed_trades[self._closed_seen:]:
            self.risk.on_close(t.pl)
        self._closed_seen = len(self.closed_trades)

        if self.position:
            trade = self.trades[-1]
            initial_risk = trade.tag  # in scaled price units
            be_r = self.strat.p["breakeven_at_r"]
            if be_r > 0 and trade.sl is not None and trade.sl < trade.entry_price:
                if self.data.High[-1] >= trade.entry_price + be_r * initial_risk:
                    trade.sl = trade.entry_price
            if i - trade.entry_bar >= self.strat.p["max_bars"] or self.strat.exit_signal(self.ind, i):
                trade.close()
            return

        if self.trade_from is not None and now < self.trade_from:
            return
        sig = self.strat.entry_signal(self.ind, i)
        if sig is None:
            return
        ok, _ = self.risk.can_open(open_positions=0)
        if not ok:
            return
        scale = self.data.Close[-1] / sig.entry
        equity = self.equity
        qty = self.risk.size(equity, sig.entry * scale, sig.stop * scale)
        fraction = min(qty * self.data.Close[-1] / equity, 0.9999) if equity > 0 else 0
        if fraction <= 0:
            return
        self.buy(size=fraction, sl=sig.stop * scale, tp=sig.target * scale, tag=sig.risk_per_unit * scale)
        self.risk.on_open()


def _make_adapter(strategy_cls: type[BaseStrategy], df: pd.DataFrame, params: dict, risk_kwargs: dict, trade_from=None):
    attrs = {**BaseStrategy.defaults, **strategy_cls.defaults, **params}
    return type(
        f"{strategy_cls.__name__}Adapter",
        (_Adapter,),
        {**attrs, "strategy_cls": strategy_cls, "source_df": df, "risk_kwargs": risk_kwargs, "trade_from": trade_from},
    )


@dataclass
class BacktestConfig:
    cash: float = 10_000.0
    commission: float = 0.001  # Binance spot taker fee per side
    slippage_bps: float = 2.0
    risk_kwargs: dict | None = None


def _bt(df: pd.DataFrame, adapter, cfg: BacktestConfig) -> FractionalBacktest:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return FractionalBacktest(
            df[["Open", "High", "Low", "Close", "Volume"]],
            adapter,
            cash=cfg.cash,
            commission=cfg.commission,
            spread=2 * cfg.slippage_bps / 1e4,
            exclusive_orders=True,
            finalize_trades=True,
            fractional_unit=FRACTIONAL_UNIT,
        )


def run_backtest(
    df: pd.DataFrame, strategy: str | type[BaseStrategy], params: dict | None = None,
    cfg: BacktestConfig | None = None, trade_from: pd.Timestamp | None = None,
) -> tuple[pd.Series, FractionalBacktest]:
    """Run one backtest. `df` is OHLCV with a UTC DatetimeIndex (see data.load_klines)."""
    cls = STRATEGIES[strategy] if isinstance(strategy, str) else strategy
    cfg = cfg or BacktestConfig()
    adapter = _make_adapter(cls, df, params or {}, cfg.risk_kwargs or {}, trade_from)
    bt = _bt(df, adapter, cfg)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stats = bt.run()
    return stats, bt


def summarize(stats: pd.Series) -> dict[str, float]:
    """Day-trading oriented metrics on top of backtesting.py's stats."""
    trades: pd.DataFrame = stats["_trades"]
    n = len(trades)
    days = max((stats["End"] - stats["Start"]).total_seconds() / 86400, 1e-9)
    if n:
        r_multiple = trades["PnL"] / (trades["Size"].abs() * trades["Tag"].astype(float) / FRACTIONAL_UNIT)
        avg_r = float(r_multiple.mean())
    else:
        avg_r = float("nan")
    return {
        "Return [%]": float(stats["Return [%]"]),
        "Buy & Hold [%]": float(stats["Buy & Hold Return [%]"]),
        "Max Drawdown [%]": float(stats["Max. Drawdown [%]"]),
        "# Trades": n,
        "Trades / day": n / days,
        "Win Rate [%]": float(stats["Win Rate [%]"]) if n else float("nan"),
        "Profit Factor": float(stats["Profit Factor"]) if n else float("nan"),
        "Expectancy [%]": float(stats["Expectancy [%]"]) if n else float("nan"),
        "Avg R": avg_r,
        "Exposure [%]": float(stats["Exposure Time [%]"]),
        "Sharpe": float(stats["Sharpe Ratio"]),
    }


def walk_forward(
    df: pd.DataFrame, strategy: str, train_days: int = 30, test_days: int = 7,
    grid: dict[str, list] | None = None, cfg: BacktestConfig | None = None,
    min_trades: int = 10, maximize: str = "SQN",
) -> tuple[pd.DataFrame, pd.Series]:
    """Rolling walk-forward: optimise on `train_days`, then trade the next `test_days` with the chosen params.

    Returns (per-fold table, stitched out-of-sample equity curve). Only the test windows count.
    """
    cls = STRATEGIES[strategy]
    cfg = cfg or BacktestConfig()
    grid = grid or cls.param_grid
    if not grid:
        raise ValueError(f"{strategy} has no param_grid")
    bar = df.index[1] - df.index[0]
    warmup = cls().warmup_bars(bar) * bar
    start = df.index[0] + warmup
    folds, equity_parts = [], []
    capital = cfg.cash

    while True:
        train_start, train_end = start, start + pd.Timedelta(days=train_days)
        test_end = train_end + pd.Timedelta(days=test_days)
        if test_end > df.index[-1] + bar:
            break
        train = df[(df.index >= train_start - warmup) & (df.index < train_end)]
        adapter = _make_adapter(cls, train, {}, cfg.risk_kwargs or {}, trade_from=train_start)
        bt = _bt(train, adapter, cfg)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            best = bt.optimize(
                **grid,
                maximize=lambda s: (s[maximize] if s["# Trades"] >= min_trades and not np.isnan(s[maximize]) else -np.inf),
            )
        best_params = {k: getattr(best["_strategy"], k) for k in grid}

        test = df[(df.index >= train_end - warmup) & (df.index < test_end)]
        stats, _ = run_backtest(
            test, cls, best_params,
            BacktestConfig(capital, cfg.commission, cfg.slippage_bps, cfg.risk_kwargs), trade_from=train_end,
        )
        eq = stats["_equity_curve"]["Equity"]
        eq = eq[eq.index >= train_end]
        equity_parts.append(eq)
        capital = float(eq.iloc[-1]) if len(eq) else capital
        folds.append({
            "train_start": train_start, "test_start": train_end, "test_end": test_end,
            **best_params,
            "train_score": float(best[maximize]) if best["# Trades"] >= min_trades else float("nan"),
            "test_return_%": (eq.iloc[-1] / eq.iloc[0] - 1) * 100 if len(eq) else 0.0,
            "test_trades": int(len(stats["_trades"])),
        })
        start += pd.Timedelta(days=test_days)

    equity = pd.concat(equity_parts) if equity_parts else pd.Series(dtype=float)
    return pd.DataFrame(folds), equity
