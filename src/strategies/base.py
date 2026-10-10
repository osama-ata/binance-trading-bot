"""Strategy interface shared by the backtester and the live engine.

A strategy is long-only (spot). `prepare()` adds *causal* indicator columns to an OHLCV frame
(Open/High/Low/Close/Volume, UTC open-time index). `entry_signal()` and `exit_signal()` read a single
row `i` of that frame, which is always a *closed* bar, so backtest and live see exactly the same inputs.
"""
from collections import Counter
from dataclasses import dataclass
from typing import Any, ClassVar

import pandas as pd

import indicators as ta


@dataclass(frozen=True)
class Signal:
    entry: float  # reference price (the signal bar's close); actual fill happens on the next bar
    stop: float
    target: float
    reason: str

    @property
    def risk_per_unit(self) -> float:
        return self.entry - self.stop


class BaseStrategy:
    name: ClassVar[str] = "base"
    # Default parameters; any key can be overridden via constructor kwargs or the optimizer
    defaults: ClassVar[dict[str, Any]] = {
        "atr_n": 14,
        "stop_atr": 1.5,
        "rr": 2.0,
        "breakeven_at_r": 1.0,  # move stop to fee-adjusted break-even once price has moved this many R (0 = off)
        "max_bars": 48,  # time stop
        # Stops use ATR from this (higher) timeframe so they clear the fee hurdle; None = signal timeframe
        "atr_tf": "1h",
        # Fee hurdle gates, in multiples of the round-trip fee (2 x fee_rate)
        "min_stop_fee_mult": 4.0,  # stop distance must be >= 4 round trips (fees <= 0.25R)
        "min_target_fee_mult": 5.0,  # target distance must be >= 5 round trips
        "min_atr_pct": 0.0,  # skip entries when signal-timeframe ATR% is below this (0 = off)
    }
    # Grid used by the walk-forward optimizer
    param_grid: ClassVar[dict[str, list[Any]]] = {}

    def __init__(self, fee_rate: float = 0.001, **params: Any):
        merged = {**BaseStrategy.defaults, **self.defaults}
        unknown = set(params) - set(merged)
        if unknown:
            raise ValueError(f"Unknown params for {self.name}: {sorted(unknown)}")
        self.p: dict[str, Any] = {**merged, **params}
        self.fee_rate = fee_rate  # per side; set from settings.fee_rate / BacktestConfig.commission
        self.rejected: Counter[str] = Counter()  # signals dropped by the fee / volatility gates

    def indicator_warmup(self, bar: pd.Timedelta) -> int:
        """Bars needed by the strategy's own indicators. Override in subclasses."""
        return 250

    def warmup_bars(self, bar: pd.Timedelta) -> int:
        """Bars of history (of size `bar`) needed before all indicators are valid."""
        ratio = self._atr_tf_ratio(bar)
        return max(self.indicator_warmup(bar), int(1.5 * self.p["atr_n"] * ratio) + ratio)

    def _atr_tf_ratio(self, bar: pd.Timedelta) -> int:
        tf = self.p["atr_tf"]
        return max(1, int(pd.Timedelta(tf) / bar)) if tf else 1

    # ----- to implement -----
    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        raise NotImplementedError

    def entry(self, row: pd.Series, prev: pd.Series) -> str | None:
        """Return a reason string to go long on this closed bar, else None."""
        raise NotImplementedError

    def target_for(self, row: pd.Series, stop: float) -> float:
        return row["Close"] + self.p["rr"] * (row["Close"] - stop)

    def exit(self, row: pd.Series) -> str | None:
        """Optional discretionary exit (besides stop / target / time stop)."""
        return None

    # ----- shared plumbing -----
    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["atr_base"] = ta.atr(df, self.p["atr_n"])
        bar = df.index[1] - df.index[0] if len(df) > 1 else None
        if bar is not None and self._atr_tf_ratio(bar) > 1:
            n = self.p["atr_n"]
            out["atr"] = ta.higher_tf(df, self.p["atr_tf"], lambda h: ta.atr(h, n))
        else:
            out["atr"] = out["atr_base"]
        for k, v in self.indicators(df).items():
            out[k] = v
        return out

    def entry_signal(self, ind: pd.DataFrame, i: int) -> Signal | None:
        if i < 1:
            return None
        row, prev = ind.iloc[i], ind.iloc[i - 1]
        if row.isna().any():
            return None
        reason = self.entry(row, prev)
        if not reason:
            return None
        close = row["Close"]
        stop = self.stop_for(row)
        if not stop < close:
            return None
        target = self.target_for(row, stop)
        if not target > close:
            return None
        round_trip = 2 * self.fee_rate
        if (close - stop) / close < self.p["min_stop_fee_mult"] * round_trip:
            self.rejected["stop below fee hurdle"] += 1
            return None
        if (target - close) / close < self.p["min_target_fee_mult"] * round_trip:
            self.rejected["target below fee hurdle"] += 1
            return None
        if row["atr_base"] / close < self.p["min_atr_pct"]:
            self.rejected["low volatility"] += 1
            return None
        return Signal(entry=float(close), stop=float(stop), target=float(target), reason=reason)

    def stop_for(self, row: pd.Series) -> float:
        return row["Close"] - self.p["stop_atr"] * row["atr"]

    def exit_signal(self, ind: pd.DataFrame, i: int) -> str | None:
        return self.exit(ind.iloc[i])
