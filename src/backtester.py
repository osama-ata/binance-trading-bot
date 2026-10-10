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

from risk import RiskManager, breakeven_stop
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
    fee_rate: float = 0.001  # per side, mirrors BacktestConfig.commission
    slippage: float = 0.0  # per side, mirrors the backtest `spread`

    def init(self):
        names = {**BaseStrategy.defaults, **self.strategy_cls.defaults}
        self.strat = self.strategy_cls(
            fee_rate=self.fee_rate, **{k: getattr(self, k) for k in names if hasattr(self, k)}
        )
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
            if trade.sl is not None:  # same rule as the live engine (risk.breakeven_stop); prices are scaled
                new_sl = breakeven_stop(trade.entry_price, trade.sl, trade.tag, self.data.High[-1],
                                        self.strat.p["breakeven_at_r"], self.fee_rate, self.slippage)
                if new_sl != trade.sl:
                    trade.sl = new_sl
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
        fill = self.data.Close[-1] * (1 + self.slippage)  # backtesting.py validates SL < fill < TP
        if not sig.stop * scale < fill < sig.target * scale:
            return
        self.buy(size=fraction, sl=sig.stop * scale, tp=sig.target * scale, tag=sig.risk_per_unit * scale)
        self.risk.on_open()


def _make_adapter(strategy_cls: type[BaseStrategy], df: pd.DataFrame, params: dict, cfg: "BacktestConfig",
                  trade_from=None):
    attrs = {**BaseStrategy.defaults, **strategy_cls.defaults, **params}
    return type(
        f"{strategy_cls.__name__}Adapter",
        (_Adapter,),
        {**attrs, "strategy_cls": strategy_cls, "source_df": df, "risk_kwargs": cfg.risk_kwargs or {},
         "trade_from": trade_from, "fee_rate": cfg.commission, "slippage": cfg.slippage_bps / 1e4},
    )


@dataclass
class BacktestConfig:
    cash: float = 10_000.0
    commission: float = 0.001  # Binance spot taker fee per side
    slippage_bps: float = 2.0  # per side (backtesting.py applies `spread` on every fill)
    risk_kwargs: dict | None = None


def _bt(df: pd.DataFrame, adapter, cfg: BacktestConfig) -> FractionalBacktest:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return FractionalBacktest(
            df[["Open", "High", "Low", "Close", "Volume"]],
            adapter,
            cash=cfg.cash,
            commission=cfg.commission,
            spread=cfg.slippage_bps / 1e4,
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
    adapter = _make_adapter(cls, df, params or {}, cfg, trade_from)
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
    nan = float("nan")
    avg_r = gross_r = fees_r = eff_risk = cap_bound = nan
    if n:
        risk_cash = trades["Size"].abs() * trades["Tag"].astype(float) / FRACTIONAL_UNIT  # $ at risk per trade
        avg_r = float((trades["PnL"] / risk_cash).mean())
        fees_r = float((trades["Commission"] / risk_cash).mean())
        gross_r = float(((trades["PnL"] + trades["Commission"]) / risk_cash).mean())
        equity = stats["_equity_curve"]["Equity"]
        equity_at_entry = equity.iloc[trades["EntryBar"].clip(upper=len(equity) - 1)].to_numpy()
        eff = risk_cash.to_numpy() / equity_at_entry
        eff_risk = float(eff.mean() * 100)
        target_risk = stats["_strategy"].risk.risk_per_trade
        cap_bound = float((eff < 0.95 * target_risk).mean() * 100)  # share of trades sized by the notional cap
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
        "Gross Avg R": gross_r,
        "Fees [R]": fees_r,
        "Effective risk [%]": eff_risk,
        "Cap-bound trades [%]": cap_bound,
        "Exposure [%]": float(stats["Exposure Time [%]"]),
        "Sharpe": float(stats["Sharpe Ratio"]),
    }


def walk_forward(
    df: pd.DataFrame, strategy: str, train_days: int = 30, test_days: int = 7,
    grid: dict[str, list] | None = None, cfg: BacktestConfig | None = None,
    min_trades: int = 10, maximize: str = "SQN", params: dict | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Rolling walk-forward: optimise on `train_days`, then trade the next `test_days` with the chosen params.

    `params` are fixed overrides applied in every fold (e.g. {"signal_tf": "1h"}); `grid` is what's optimised.
    Returns (per-fold table, stitched out-of-sample equity curve). Only the test windows count.
    """
    params = params or {}
    cls = STRATEGIES[strategy]
    cfg = cfg or BacktestConfig()
    grid = grid or cls.param_grid
    if not grid:
        raise ValueError(f"{strategy} has no param_grid")
    bar = df.index[1] - df.index[0]
    warmup = cls(**params).warmup_bars(bar) * bar
    start = df.index[0] + warmup
    folds, equity_parts = [], []
    capital = cfg.cash

    while True:
        train_start, train_end = start, start + pd.Timedelta(days=train_days)
        test_end = train_end + pd.Timedelta(days=test_days)
        if test_end > df.index[-1] + bar:
            break
        train = df[(df.index >= train_start - warmup) & (df.index < train_end)]
        adapter = _make_adapter(cls, train, params, cfg, trade_from=train_start)
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
            test, cls, {**params, **best_params},
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


def grid_returns(
    df: pd.DataFrame, strategy: str, grid: dict[str, list] | None = None, cfg: BacktestConfig | None = None,
    params: dict | None = None, freq: str = "1D",
) -> pd.DataFrame:
    """Per-period (default daily) returns of every grid combination over the whole of `df` (after warm-up).

    This T x N matrix is the input for PBO/CSCV and for the trial-Sharpe variance used by the Deflated Sharpe.
    """
    from itertools import product

    from overfitting import period_returns

    cls = STRATEGIES[strategy]
    grid = grid or cls.param_grid
    params = params or {}
    bar = df.index[1] - df.index[0]
    trade_from = df.index[0] + cls(**params).warmup_bars(bar) * bar
    cols = {}
    for values in product(*grid.values()):
        combo = dict(zip(grid, values))
        stats, _ = run_backtest(df, cls, {**params, **combo}, cfg, trade_from=trade_from)
        eq = stats["_equity_curve"]["Equity"]
        cols[", ".join(f"{k}={v}" for k, v in combo.items())] = period_returns(eq[eq.index >= trade_from], freq)
    return pd.DataFrame(cols).fillna(0.0)


def overfitting_report(df: pd.DataFrame, strategy: str, oos_equity: pd.Series, cfg: BacktestConfig | None = None,
                       params: dict | None = None, n_blocks: int = 16) -> dict:
    """PBO (CSCV over the full-period grid) and Deflated Sharpe of the stitched walk-forward OOS equity."""
    from overfitting import deflated_sharpe, pbo_cscv, period_returns, probabilistic_sharpe, sharpe

    m = grid_returns(df, strategy, cfg=cfg, params=params)
    trial_srs = [sharpe(m[c]) for c in m.columns]
    oos = period_returns(oos_equity) if len(oos_equity) else pd.Series(dtype=float)
    out = {"n_trials": m.shape[1], "n_days": m.shape[0]}
    out.update(pbo_cscv(m, n_blocks=n_blocks))
    out["oos_sharpe_ann"] = sharpe(oos) * np.sqrt(365) if len(oos) > 2 else float("nan")
    out["psr"] = probabilistic_sharpe(oos) if len(oos) > 2 else float("nan")
    out["dsr"] = deflated_sharpe(oos, trial_srs) if len(oos) > 2 else float("nan")
    return out
