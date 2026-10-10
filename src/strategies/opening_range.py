import numpy as np
import pandas as pd

from strategies.base import BaseStrategy


class OpeningRangeBreakout(BaseStrategy):
    """Opening-range breakout around a session open in a given time zone (default 09:30 America/New_York, the
    US equity open: 13:30 UTC under US daylight time, 14:30 UTC in winter). Set `session_tz="UTC"` to pin
    the open to a fixed UTC time.

    The range is the high/low of the first `range_minutes` after the open. Go long on the first close above
    the range high within `entry_window_minutes`; stop at the range low (capped by ATR), target at rr * R.
    """

    name = "opening_range"
    defaults = {
        "session_open": "09:30",
        "session_tz": "America/New_York",
        "range_minutes": 30,
        "entry_window_minutes": 240,
        "max_stop_atr": 2.0,
        "rr": 2.0,
        "max_bars": 48,
    }
    param_grid = {"range_minutes": [15, 30, 60], "rr": [1.5, 2.0, 3.0], "max_stop_atr": [1.5, 2.0, 3.0]}

    def indicator_warmup(self, bar) -> int:
        return 300

    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        hh, mm = map(int, self.p["session_open"].split(":"))
        bar = df.index[1] - df.index[0] if len(df) > 1 else pd.Timedelta(minutes=5)
        local = df.index.tz_convert(self.p["session_tz"])
        local_day = local.normalize()  # local midnight, so DST is handled per day
        day = local_day.tz_localize(None)  # session key: the local calendar date
        open_t = (local_day + pd.Timedelta(hours=hh, minutes=mm)).tz_convert(df.index.tz)
        range_end = open_t + pd.Timedelta(minutes=self.p["range_minutes"])
        in_range = (df.index >= open_t) & (df.index + bar <= range_end)
        hi = df["High"].where(in_range).groupby(day).cummax()
        lo = df["Low"].where(in_range).groupby(day).cummin()
        # Only expose the range once it is complete (bar closes after range_end)
        complete = df.index + bar > range_end
        window = df.index + bar <= range_end + pd.Timedelta(minutes=self.p["entry_window_minutes"])
        or_high = hi.groupby(day).ffill().where(complete & window)
        or_low = lo.groupby(day).ffill().where(complete & window)
        # first breakout of the day only
        above = (df["Close"] > or_high).astype(int)
        first = above.groupby(day).cumsum() == 1
        return {
            "or_high": or_high,
            "or_low": or_low,
            "or_first_break": pd.Series(np.where(first & (above == 1), 1.0, 0.0), index=df.index).where(
                or_high.notna()
            ),
        }

    def entry(self, row: dict, prev: dict) -> str | None:
        if row["or_first_break"] == 1.0:
            return f"opening range breakout above {row['or_high']:.2f}"
        return None

    def stop_for(self, row: dict) -> float:
        return max(row["or_low"], row["Close"] - self.p["max_stop_atr"] * row["atr"])
