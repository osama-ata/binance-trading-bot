"""Historical OHLCV loader.

Bulk history comes from Binance's public archive (data.binance.vision): one zip per month, plus daily
zips for the current month. The last day or so, which isn't archived yet, is filled from the REST klines
endpoint. Each period is cached under data/klines/ as Parquet.
"""
import io
import logging
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from binance_client import KLINE_COLUMNS, BinanceClient, interval_to_timedelta, klines_to_df

log = logging.getLogger(__name__)

ARCHIVE = "https://data.binance.vision/data/spot"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "klines"


def _download_zip(url: str) -> pd.DataFrame | None:
    r = requests.get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = pd.read_csv(z.open(z.namelist()[0]), header=None)
    # Some older archive files include a header row
    if not str(raw.iloc[0, 0]).isdigit():
        raw = raw.iloc[1:]
    return klines_to_df(raw.values.tolist())


def _cached(symbol: str, interval: str, period: str, url: str, persist: bool) -> pd.DataFrame | None:
    path = CACHE_DIR / symbol / interval / f"{period}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = _download_zip(url)
    if df is not None and persist:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
    return df


def _month_starts(start: date, end: date):
    d = start.replace(day=1)
    while d <= end:
        yield d
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def load_klines(
    symbol: str, interval: str, start: date | str, end: date | str | None = None, client: BinanceClient | None = None
) -> pd.DataFrame:
    """Return OHLCV (Open/High/Low/Close/Volume, UTC open-time index) for [start, end] inclusive."""
    symbol = symbol.upper().replace("/", "")
    start = pd.Timestamp(start).date()
    today = datetime.now(timezone.utc).date()
    end = min(pd.Timestamp(end).date() if end else today, today)
    this_month = today.replace(day=1)

    frames: list[pd.DataFrame] = []
    for m in _month_starts(start, end):
        if m < this_month:
            tag = f"{m:%Y-%m}"
            url = f"{ARCHIVE}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{tag}.zip"
            df = _cached(symbol, interval, tag, url, persist=True)
            if df is not None:
                frames.append(df)
                continue
        # Current month (or a month not yet archived): use daily files
        d = max(m, start)
        month_end = (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        while d <= min(month_end, end, today - timedelta(days=1)):
            tag = f"{d:%Y-%m-%d}"
            url = f"{ARCHIVE}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{tag}.zip"
            df = _cached(symbol, interval, tag, url, persist=True)
            if df is not None:
                frames.append(df)
            d += timedelta(days=1)

    out = pd.concat(frames) if frames else pd.DataFrame(columns=KLINE_COLUMNS)

    # Fill the not-yet-archived tail from REST (paginated, 1000 bars per call)
    end_ts = pd.Timestamp(end + timedelta(days=1), tz="UTC")
    since = out.index.max() + pd.Timedelta(milliseconds=1) if len(out) else pd.Timestamp(start, tz="UTC")
    if since < end_ts:
        client = client or BinanceClient()
        while since < end_ts:
            chunk = client.get_klines(
                symbol, interval, limit=1000,
                start_ms=int(since.timestamp() * 1000), end_ms=int(end_ts.timestamp() * 1000) - 1,
            )
            if chunk.empty:
                break
            out = pd.concat([out, chunk])
            since = chunk.index.max() + pd.Timedelta(milliseconds=1)
            if len(chunk) < 1000:
                break

    out = out[~out.index.duplicated(keep="last")].sort_index()
    # Drop the still-forming candle, if any
    out = out[out.index + interval_to_timedelta(interval) <= pd.Timestamp.now(tz="UTC")]
    mask = (out.index >= pd.Timestamp(start, tz="UTC")) & (out.index < end_ts)
    return out.loc[mask].astype(float)
