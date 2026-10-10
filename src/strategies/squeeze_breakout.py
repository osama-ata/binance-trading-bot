import pandas as pd

import indicators as ta
from strategies.base import BaseStrategy


class SqueezeBreakout(BaseStrategy):
    """Volatility squeeze (Bollinger inside Keltner) followed by an upside breakout on above-average volume."""

    name = "squeeze_breakout"
    defaults = {
        "bb_n": 20,
        "bb_k": 2.0,
        "kc_k": 1.5,
        "squeeze_lookback": 6,  # squeeze must have been on within this many bars
        "vol_mult": 1.5,
        "trend_ema": 50,
        "stop_atr": 1.5,
        "rr": 2.5,
    }
    param_grid = {"kc_k": [1.25, 1.5, 2.0], "vol_mult": [1.2, 1.5, 2.0], "rr": [2.0, 2.5, 3.0]}

    def warmup_bars(self, bar) -> int:
        return 300

    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        bb_lo, _, bb_hi = ta.bollinger(df["Close"], self.p["bb_n"], self.p["bb_k"])
        kc_lo, _, kc_hi = ta.keltner(df, self.p["bb_n"], self.p["kc_k"])
        squeeze = ((bb_hi < kc_hi) & (bb_lo > kc_lo)).astype(float).where(bb_hi.notna() & kc_hi.notna())
        return {
            "bb_hi": bb_hi,
            # squeeze present in any of the previous N bars (excluding the breakout bar)
            "recent_squeeze": squeeze.shift(1).rolling(self.p["squeeze_lookback"], min_periods=1).max(),
            "vol_avg": ta.sma(df["Volume"], 20).shift(1),
            "trend": ta.ema(df["Close"], self.p["trend_ema"]),
        }

    def entry(self, row: pd.Series, prev: pd.Series) -> str | None:
        if (
            row["recent_squeeze"] == 1.0
            and row["Close"] > row["bb_hi"]
            and prev["Close"] <= prev["bb_hi"]
            and row["Volume"] > self.p["vol_mult"] * row["vol_avg"]
            and row["Close"] > row["trend"]
        ):
            return f"squeeze breakout, vol x{row['Volume'] / row['vol_avg']:.1f}"
        return None
