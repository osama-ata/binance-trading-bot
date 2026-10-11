"""Causal technical indicators (value at bar i only uses bars <= i)."""
import numpy as np
import pandas as pd


def normalize_tf(tf: str | None) -> str | None:
    """Binance-style timeframe ("15m", "1h", "1d") -> pandas offset ("15min", "1h", "1D")."""
    if not tf:
        return None
    tf = str(tf).strip()
    if tf.endswith("m") and tf[:-1].isdigit():
        return tf[:-1] + "min"
    if tf.endswith("d") and tf[:-1].isdigit():
        return tf[:-1] + "D"
    return tf


def ewm_warmup(alpha: float, tol: float = 1e-3) -> int:
    """Bars until an exponentially smoothed series has forgotten its seed to within `tol`:
    (1 - alpha)^k <= tol. EMA(span n): alpha = 2/(n+1) -> ~3.5(n+1); Wilder(n): alpha = 1/n -> ~6.9n."""
    return int(np.ceil(np.log(tol) / np.log(1 - alpha)))


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100.0).where(gain.notna())


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift()
    return pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()], axis=1
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = atr(df, n)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return mid - k * sd, mid, mid + k * sd


def keltner(df: pd.DataFrame, n: int = 20, k: float = 1.5) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = ema(df["Close"], n)
    rng = atr(df, n)
    return mid - k * rng, mid, mid + k * rng


def session_vwap(df: pd.DataFrame, anchor: str = "D") -> tuple[pd.Series, pd.Series]:
    """VWAP anchored to each UTC session (default: daily) and the volume-weighted std around it."""
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    session = df.index.floor(anchor)
    pv = (typical * df["Volume"]).groupby(session).cumsum()
    vol = df["Volume"].groupby(session).cumsum().replace(0, np.nan)
    vwap = pv / vol
    var = ((typical**2) * df["Volume"]).groupby(session).cumsum() / vol - vwap**2
    return vwap, np.sqrt(var.clip(lower=0))


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate to a higher timeframe, labelled by bar *close* so it can be joined without look-ahead."""
    out = df.resample(rule, label="right", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    return out.dropna(subset=["Close"])


def higher_tf(df: pd.DataFrame, rule: str, series_fn) -> pd.Series:
    """Compute series_fn on a higher timeframe and forward-fill onto df's index using only *closed* HTF bars.

    df's index is bar open time; a base bar opening at t is closed at t + base_period, so it may see
    HTF bars whose close label <= t + base_period.
    """
    htf = resample_ohlcv(df, rule)
    values = series_fn(htf)
    # The last HTF bucket may still be forming; drop it unless df fully covers it.
    if len(df) > 1:
        base_period = df.index[1] - df.index[0]
        values = values[values.index <= df.index[-1] + base_period]
    base_close_times = df.index + (df.index[1] - df.index[0] if len(df) > 1 else pd.Timedelta(0))
    aligned = values.reindex(values.index.union(base_close_times)).ffill()
    return pd.Series(aligned.reindex(base_close_times).to_numpy(), index=df.index)


def align_higher_tf(df: pd.DataFrame, rule: str, frame_fn) -> tuple[pd.DataFrame, pd.Series]:
    """Run `frame_fn` on `df` resampled to `rule` (indexed by bar *open* time, like df) and forward-fill the
    resulting columns onto df's bars using only *closed* higher-timeframe bars.

    Returns (aligned frame indexed like df, boolean Series that is True on the base bars that complete a
    higher-timeframe bar, i.e. where a fresh value appears).
    """
    if len(df) < 2:
        empty = frame_fn(df.iloc[0:0])
        return empty.reindex(df.index), pd.Series(False, index=df.index)
    base_period = df.index[1] - df.index[0]
    period = pd.Timedelta(rule)
    htf = df.resample(rule, label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna(subset=["Close"])
    frame = frame_fn(htf)
    frame.index = frame.index + period  # label by close time
    frame = frame[frame.index <= df.index[-1] + base_period]  # drop the still-forming bucket
    base_close = df.index + base_period
    aligned = frame.reindex(frame.index.union(base_close)).ffill().reindex(base_close)
    aligned.index = df.index
    is_close = pd.Series(base_close.isin(frame.index), index=df.index)
    return aligned, is_close


def realized_vol(close: pd.Series, n: int, bar: pd.Timedelta) -> pd.Series:
    """Annualised realized volatility: std of the last `n` log returns, scaled by sqrt(bars per year)."""
    per_year = pd.Timedelta(days=365) / bar
    return np.log(close).diff().rolling(n, min_periods=n).std() * np.sqrt(per_year)


def efficiency_ratio(close: pd.Series, n: int) -> pd.Series:
    """Kaufman Efficiency Ratio: net move over the sum of absolute moves in the last `n` bars (0 = chop, 1 = trend)."""
    path = close.diff().abs().rolling(n, min_periods=n).sum()
    return (close - close.shift(n)).abs() / path.where(path > 0)


def choppiness(df: pd.DataFrame, n: int) -> pd.Series:
    """Choppiness Index (0-100): high = ranging, low = trending."""
    tr_sum = true_range(df).rolling(n, min_periods=n).sum()
    span = df["High"].rolling(n, min_periods=n).max() - df["Low"].rolling(n, min_periods=n).min()
    return 100 * np.log10(tr_sum / span.where(span > 0)) / np.log10(n)


def vol_percentile(close: pd.Series, n: int, window: int) -> pd.Series:
    """Percentile rank (0-1) of the current `n`-bar realized volatility within the trailing `window` bars."""
    rv = np.log(close).diff().rolling(n, min_periods=n).std()
    return rv.rolling(window, min_periods=window).rank(pct=True)
