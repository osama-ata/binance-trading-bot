import numpy as np
import pandas as pd

from strategies.base import BaseStrategy


class DonchianEnsemble(BaseStrategy):
    """Trend following with an ensemble of Donchian-channel breakouts (cf. Zarattini, Pagani & Barbon,
    SFI RP 25-80, which reports the best net-of-cost crypto evidence for this family on multi-hour bars).

    Each lookback L is a component that is long when its most recent channel event within the last L bars was a
    close above the prior L-bar high (rather than a close below the prior L/2-bar low). The ensemble score is the share of components that are long.
    Enter when the score crosses up through `entry_threshold`; exit when it falls to `exit_threshold`.
    The stop is wide (ATR-based) and the target far away, so exits are mostly signal- or time-driven.
    Runs on 1h signals by default; `max_bars` counts *engine* bars (5m by default: 2016 = 7 days).
    """

    name = "donchian_ensemble"
    defaults = {
        "signal_tf": "1h",
        "lookbacks": "24,48,96,192,384",  # in signal bars (1 to 16 days on 1h)
        "entry_threshold": 0.6,
        "exit_threshold": 0.2,
        "stop_atr": 3.0,
        "rr": 10.0,
        "breakeven_at_r": 0.0,
        "max_bars": 2016,
    }
    param_grid = {"entry_threshold": [0.4, 0.6, 0.8], "exit_threshold": [0.0, 0.2, 0.4], "stop_atr": [2.0, 3.0, 4.0]}

    def _lookbacks(self) -> list[int]:
        return [int(x) for x in str(self.p["lookbacks"]).split(",")]

    def indicator_warmup(self, bar) -> int:
        return 2 * max(self._lookbacks()) + 2  # channel window (L) + bounded state memory (L)

    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        close = df["Close"]
        states = []
        for n in self._lookbacks():
            upper = df["High"].rolling(n, min_periods=n).max().shift(1)
            lower = df["Low"].rolling(max(n // 2, 1), min_periods=max(n // 2, 1)).min().shift(1)
            # Long if the most recent channel event within the last n bars was an upside breakout. Bounding the
            # memory to n bars keeps the state independent of how much history is loaded (live == backtest).
            pos = pd.Series(np.arange(len(df), dtype=float), index=df.index)
            last_up = pos.where(close > upper).ffill(limit=n)
            last_dn = pos.where(close < lower).ffill(limit=n)
            state = (last_up.notna() & (last_up > last_dn.fillna(-1.0))).astype(float).where(upper.notna())
            states.append(state)
        score = pd.concat(states, axis=1).mean(axis=1, skipna=False)
        return {"trend_score": score}

    def entry(self, row: dict, prev: dict) -> str | None:
        if prev["trend_score"] < self.p["entry_threshold"] <= row["trend_score"]:
            return f"donchian ensemble score {prev['trend_score']:.2f}->{row['trend_score']:.2f}"
        return None

    def exit(self, row: dict) -> str | None:
        return "trend score faded" if row["trend_score"] <= self.p["exit_threshold"] else None
