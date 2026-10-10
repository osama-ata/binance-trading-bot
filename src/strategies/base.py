"""Strategy interface shared by the backtester and the live engine.

A strategy is long-only (spot). `prepare()` adds *causal* indicator columns to an OHLCV frame
(Open/High/Low/Close/Volume, UTC open-time index). `entry_signal()` and `exit_signal()` read a single
row `i` of that frame, which is always a *closed* bar, so backtest and live see exactly the same inputs.
"""
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
        "breakeven_at_r": 1.0,  # move stop to entry once price has moved this many R (0 = off)
        "max_bars": 48,  # time stop
    }
    # Grid used by the walk-forward optimizer
    param_grid: ClassVar[dict[str, list[Any]]] = {}

    def __init__(self, **params: Any):
        merged = {**BaseStrategy.defaults, **self.defaults}
        unknown = set(params) - set(merged)
        if unknown:
            raise ValueError(f"Unknown params for {self.name}: {sorted(unknown)}")
        self.p: dict[str, Any] = {**merged, **params}

    def warmup_bars(self, bar: pd.Timedelta) -> int:
        """Bars of history (of size `bar`) needed before indicators are valid."""
        return 250

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
        out["atr"] = ta.atr(df, self.p["atr_n"])
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
        stop = self.stop_for(row)
        if not stop < row["Close"]:
            return None
        target = self.target_for(row, stop)
        if not target > row["Close"]:
            return None
        return Signal(entry=float(row["Close"]), stop=float(stop), target=float(target), reason=reason)

    def stop_for(self, row: pd.Series) -> float:
        return row["Close"] - self.p["stop_atr"] * row["atr"]

    def exit_signal(self, ind: pd.DataFrame, i: int) -> str | None:
        return self.exit(ind.iloc[i])
