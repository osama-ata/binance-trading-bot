import pandas as pd

import indicators as ta
from strategies.base import BaseStrategy


class EmaPullback(BaseStrategy):
    """Trend-following pullback.

    Higher-timeframe trend filter (EMA fast > slow on `htf`), a rising local slow EMA and ADX showing a trend.
    Entry when, after a dip (RSI below `rsi_low` within the last `dip_bars`), price closes back above the
    fast EMA, i.e. buy the reclaim of a pullback inside an uptrend.
    """

    name = "ema_pullback"
    defaults = {
        "fast": 9,
        "slow": 21,
        "htf": "1h",
        "htf_fast": 50,
        "htf_slow": 200,
        "rsi_n": 14,
        "rsi_low": 40,
        "dip_bars": 6,
        "adx_min": 18,
        "stop_atr": 2.0,  # x 1h ATR (see BaseStrategy atr_tf)
        "rr": 2.0,
    }
    param_grid = {"rsi_low": [35, 40, 45], "stop_atr": [2.0, 2.5, 3.0], "rr": [1.5, 2.0, 3.0]}

    def indicator_warmup(self, bar: pd.Timedelta) -> int:
        # The HTF slow EMA must converge (to 0.1%) on higher-timeframe bars: ~3.5 x (htf_slow + 1) of them
        htf_ratio = max(1, int(pd.Timedelta(self.p["htf"]) / bar))
        return max(250, (ta.ewm_warmup(2 / (self.p["htf_slow"] + 1)) + 1) * htf_ratio)

    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        close = df["Close"]
        ema_slow = ta.ema(close, self.p["slow"])
        rsi = ta.rsi(close, self.p["rsi_n"])
        return {
            "ema_fast": ta.ema(close, self.p["fast"]),
            "ema_slow": ema_slow,
            "slow_slope": ema_slow - ema_slow.shift(5),
            "rsi": rsi,
            "recent_rsi_min": rsi.shift(1).rolling(self.p["dip_bars"]).min(),
            "adx": ta.adx(df, 14),
            "htf_trend": ta.higher_tf(
                df,
                self.p["htf"],
                lambda h: (ta.ema(h["Close"], self.p["htf_fast"]) > ta.ema(h["Close"], self.p["htf_slow"])).astype(float)
                .where(ta.ema(h["Close"], self.p["htf_slow"]).notna()),
            ),
        }

    def entry(self, row: dict, prev: dict) -> str | None:
        if (
            row["htf_trend"] == 1.0
            and row["slow_slope"] > 0
            and row["adx"] >= self.p["adx_min"]
            and row["recent_rsi_min"] < self.p["rsi_low"]
            and prev["Close"] <= prev["ema_fast"]
            and row["Close"] > row["ema_fast"]
        ):
            return f"pullback reclaim, rsi low {row['recent_rsi_min']:.0f}, adx {row['adx']:.0f}"
        return None
