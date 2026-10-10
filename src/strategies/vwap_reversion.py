import pandas as pd

import indicators as ta
from strategies.base import BaseStrategy


class VwapReversion(BaseStrategy):
    """Mean reversion to the daily (UTC) session VWAP, only in a range regime (low ADX).

    Long when price closes below VWAP - k*sigma, RSI is oversold and the bar closes green.
    Target is the VWAP itself (the base class rejects it if it is too close to clear fees); also exits early
    if price closes back above VWAP.
    """

    name = "vwap_reversion"
    defaults = {
        "band_k": 2.0,
        "rsi_n": 14,
        "rsi_max": 30,
        "adx_max": 22,
        "stop_atr": 2.0,  # x 1h ATR (see BaseStrategy atr_tf)
        "max_bars": 36,
    }
    param_grid = {"band_k": [1.5, 2.0, 2.5], "rsi_max": [25, 30, 35], "stop_atr": [1.5, 2.0, 2.5]}

    def indicator_warmup(self, bar) -> int:
        return 300

    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        vwap, sd = ta.session_vwap(df)
        return {
            "vwap": vwap,
            "vwap_lower": vwap - self.p["band_k"] * sd,
            "rsi": ta.rsi(df["Close"], self.p["rsi_n"]),
            "adx": ta.adx(df, 14),
        }

    def entry(self, row: pd.Series, prev: pd.Series) -> str | None:
        if (
            row["Close"] < row["vwap_lower"]
            and row["rsi"] <= self.p["rsi_max"]
            and row["adx"] <= self.p["adx_max"]
            and row["Close"] > row["Open"]
        ):
            return f"vwap stretch {100 * (row['Close'] / row['vwap'] - 1):.2f}%, rsi {row['rsi']:.0f}"
        return None

    def target_for(self, row: pd.Series, stop: float) -> float:
        return row["vwap"]

    def exit(self, row: pd.Series) -> str | None:
        return "closed above vwap" if row["Close"] >= row["vwap"] else None
