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
    # Volatility targeting: position notional as a fraction of equity (None = size from the stop distance)
    size_frac: float | None = None

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
        # Evaluate entries/exits on this (slower) timeframe while execution and stop/target checks stay on the
        # engine's bar size; None = the engine's bar size. Signals fire only on bars that close a signal_tf bar.
        "signal_tf": None,
        # Stops use ATR from this (higher) timeframe so they clear the fee hurdle; None = signal timeframe
        "atr_tf": "1h",
        # Fee hurdle gates, in multiples of the round-trip fee (2 x fee_rate)
        "min_stop_fee_mult": 4.0,  # stop distance must be >= 4 round trips (fees <= 0.25R)
        "min_target_fee_mult": 5.0,  # target distance must be >= 5 round trips
        "min_atr_pct": 0.0,  # skip entries when signal-timeframe ATR% is below this (0 = off)
        # Volatility-targeted sizing (TODO 3.5): notional = vol_target / realized vol (annualised, from the last
        # vol_lookback signal-bar log returns), still capped by max_position_pct. 0 = off (stop-distance sizing).
        "vol_target": 0.0,
        "vol_lookback": 30,
        # Regime filters (TODO 5.5), computed on closed `regime_tf` bars; entries are skipped outside the band.
        # Defaults leave every filter off.
        "regime_tf": "1h",
        "er_n": 24,  # Kaufman Efficiency Ratio lookback (regime bars)
        "er_min": 0.0,
        "er_max": 1.0,
        "chop_n": 24,  # Choppiness Index lookback (regime bars)
        "chop_min": 0.0,
        "chop_max": 100.0,
        "rv_n": 24,  # realized-vol lookback, ranked against the trailing rv_pct_window regime bars
        "rv_pct_window": 720,
        "rv_pct_min": 0.0,
        "rv_pct_max": 1.0,
        # Time-of-day gate (TODO 5.2), a volatility filter only: "13-17" allows entries on bars that close in
        # [13:00, 17:00) UTC; wraps past midnight if start > end. None = any hour.
        "trade_hours": None,
    }
    # Grid used by the walk-forward optimizer
    param_grid: ClassVar[dict[str, list[Any]]] = {}

    def __init__(self, fee_rate: float = 0.001, **params: Any):
        merged = {**BaseStrategy.defaults, **self.defaults}
        unknown = set(params) - set(merged)
        if unknown:
            raise ValueError(f"Unknown params for {self.name}: {sorted(unknown)}")
        self.p: dict[str, Any] = {**merged, **params}
        for key in ("signal_tf", "atr_tf", "htf", "regime_tf"):
            if key in self.p:
                self.p[key] = ta.normalize_tf(self.p[key])
        self.fee_rate = fee_rate  # per side; set from settings.fee_rate / BacktestConfig.commission
        self.rejected: Counter[str] = Counter()  # signals dropped by the fee / volatility gates

    def indicator_warmup(self, bar: pd.Timedelta) -> int:
        """Bars needed by the strategy's own indicators. Override in subclasses."""
        return 250

    def warmup_bars(self, bar: pd.Timedelta) -> int:
        """Bars of history (of size `bar`) needed before all indicators are valid."""
        sig = self._ratio(bar, self.p["signal_tf"])
        atr = self._ratio(bar, self.p["atr_tf"])
        atr_bars = ta.ewm_warmup(1 / self.p["atr_n"]) + self.p["atr_n"]  # Wilder ATR on the atr_tf bars
        own = self.indicator_warmup(bar * sig)
        if self.p["vol_target"]:
            own = max(own, self.p["vol_lookback"] + 1)
        regime = 0
        if self._regime_filters():
            r = self._ratio(bar, self.p["regime_tf"])
            regime = (max(self.p["er_n"], self.p["chop_n"], self.p["rv_n"] + self.p["rv_pct_window"]) + 1) * r + r
        return max(own * sig + sig, atr_bars * atr + atr, regime)

    def _regime_filters(self) -> list[str]:
        """Regime columns that are switched on (non-default bounds)."""
        p = self.p
        on = []
        if p["er_min"] > 0 or p["er_max"] < 1:
            on.append("er")
        if p["chop_min"] > 0 or p["chop_max"] < 100:
            on.append("chop")
        if p["rv_pct_min"] > 0 or p["rv_pct_max"] < 1:
            on.append("rv_pct")
        return on

    @staticmethod
    def _ratio(bar: pd.Timedelta, tf: str | None) -> int:
        return max(1, int(pd.Timedelta(tf) / bar)) if tf else 1

    def _atr_tf_ratio(self, bar: pd.Timedelta) -> int:
        return self._ratio(bar, self.p["atr_tf"])

    # ----- to implement -----
    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        raise NotImplementedError

    def entry(self, row: dict, prev: dict) -> str | None:
        """Return a reason string to go long on this closed bar, else None."""
        raise NotImplementedError

    def target_for(self, row: dict, stop: float) -> float:
        return row["Close"] + self.p["rr"] * (row["Close"] - stop)

    def exit(self, row: dict) -> str | None:
        """Optional discretionary exit (besides stop / target / time stop)."""
        return None

    # ----- shared plumbing -----
    def _signal_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        f = df.copy()
        f["atr_base"] = ta.atr(df, self.p["atr_n"])  # signal-timeframe ATR
        if self.p["vol_target"] and len(df) > 1:
            f["rvol"] = ta.realized_vol(df["Close"], self.p["vol_lookback"], df.index[1] - df.index[0])
        for k, v in self.indicators(df).items():
            f[k] = v
        return f

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Causal indicator frame on df's bars. With `signal_tf`, OHLCV/indicator columns hold the latest *closed*
        signal-timeframe bar, `prev:<col>` the one before it, and `signal_bar` marks bars where a new one closed."""
        bar = df.index[1] - df.index[0] if len(df) > 1 else None
        n = self.p["atr_n"]
        if bar is not None and self._ratio(bar, self.p["signal_tf"]) > 1:
            def frame_fn(h: pd.DataFrame) -> pd.DataFrame:
                f = self._signal_frame(h)
                return pd.concat([f, f.shift(1).add_prefix("prev:")], axis=1)

            out, is_close = ta.align_higher_tf(df, self.p["signal_tf"], frame_fn)
            out["signal_bar"] = is_close
            sig_bar = pd.Timedelta(self.p["signal_tf"])
        else:
            out = self._signal_frame(df)
            out["signal_bar"] = True
            sig_bar = bar
        if sig_bar is not None and self._ratio(sig_bar, self.p["atr_tf"]) > 1:
            out["atr"] = ta.higher_tf(df, self.p["atr_tf"], lambda h: ta.atr(h, n))
        else:
            out["atr"] = out["atr_base"]
        rtf, p = self.p["regime_tf"], self.p
        fns = {"er": lambda h: ta.efficiency_ratio(h["Close"], p["er_n"]),
               "chop": lambda h: ta.choppiness(h, p["chop_n"]),
               "rv_pct": lambda h: ta.vol_percentile(h["Close"], p["rv_n"], p["rv_pct_window"])}
        for col in self._regime_filters():
            out[col] = ta.higher_tf(df, rtf, fns[col]) if rtf else fns[col](df)
        return out

    def _regime_ok(self, row: dict) -> bool:
        p = self.p
        bounds = {"er": (p["er_min"], p["er_max"]), "chop": (p["chop_min"], p["chop_max"]),
                  "rv_pct": (p["rv_pct_min"], p["rv_pct_max"])}
        return all(bounds[c][0] <= row[c] <= bounds[c][1] for c in self._regime_filters())

    def _hour_ok(self, ind: pd.DataFrame, i: int) -> bool:
        if not self.p["trade_hours"]:
            return True
        start, end = (int(x) for x in str(self.p["trade_hours"]).split("-"))
        bar = ind.index[1] - ind.index[0] if len(ind) > 1 else pd.Timedelta(0)
        hour = (ind.index[i] + bar).hour  # the bar's close time, when the decision is made
        return start <= hour < end if start <= end else (hour >= start or hour < end)

    def _rows(self, ind: pd.DataFrame, i: int) -> tuple[dict, dict]:
        """(row, previous signal row) as plain dicts. Rows are converted once per frame, because building a
        pandas Series per bar dominated backtest/optimiser time."""
        cache = getattr(self, "_row_cache", None)
        if cache is None or cache[0] is not ind or cache[1] != len(ind):
            prev_cols = [c for c in ind.columns if c.startswith("prev:")]
            cur_cols = [c for c in ind.columns if not c.startswith("prev:")]
            cache = (ind, len(ind), ind[cur_cols].to_dict("records"),
                     ind[prev_cols].rename(columns=lambda c: c[5:]).to_dict("records") if prev_cols else None)
            self._row_cache = cache
        rows, prevs = cache[2], cache[3]
        return rows[i], (prevs[i] if prevs is not None else rows[i - 1])

    def entry_signal(self, ind: pd.DataFrame, i: int) -> Signal | None:
        if i < 1 or not ind["signal_bar"].iloc[i]:
            return None
        row, prev = self._rows(ind, i)
        if any(v != v for v in row.values()):  # NaN check (indicators not warmed up yet)
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
        if not self._regime_ok(row):
            self.rejected["regime filter"] += 1
            return None
        if not self._hour_ok(ind, i):
            self.rejected["outside trade hours"] += 1
            return None
        size_frac = None
        if self.p["vol_target"]:
            size_frac = float(self.p["vol_target"] / row["rvol"]) if row["rvol"] > 0 else 0.0
        return Signal(entry=float(close), stop=float(stop), target=float(target), reason=reason, size_frac=size_frac)

    def stop_for(self, row: dict) -> float:
        return row["Close"] - self.p["stop_atr"] * row["atr"]

    def exit_signal(self, ind: pd.DataFrame, i: int) -> str | None:
        if not ind["signal_bar"].iloc[i]:
            return None
        return self.exit(self._rows(ind, i)[0])
