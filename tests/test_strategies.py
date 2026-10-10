import numpy as np
import pandas as pd
import pytest

import indicators as ta
from strategies import STRATEGIES


# Loosened params so every strategy fires on the synthetic series
LOOSE = {
    "ema_pullback": {"htf_fast": 10, "htf_slow": 30, "adx_min": 0, "rsi_low": 50},
    "vwap_reversion": {"band_k": 1.0, "rsi_max": 50, "adx_max": 100},
    "squeeze_breakout": {},
    "opening_range": {},
    "donchian_ensemble": {"lookbacks": "12,24,48", "signal_tf": "15min"},
}


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_indicators_have_no_lookahead(name, ohlcv):
    """Indicators computed on a prefix must equal the same rows computed on the full history."""
    strat = STRATEGIES[name](**LOOSE[name])
    full = strat.prepare(ohlcv)
    for cut in (1500, 2777, 3999):
        part = strat.prepare(ohlcv.iloc[:cut])
        pd.testing.assert_frame_equal(part, full.iloc[:cut], check_freq=False, rtol=1e-9, atol=1e-6)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_signals_are_well_formed(name, ohlcv):
    strat = STRATEGIES[name](**LOOSE[name])
    ind = strat.prepare(ohlcv)
    signals = [s for i in range(len(ind)) if (s := strat.entry_signal(ind, i))]
    assert signals, f"{name} produced no signals"
    for s in signals:
        assert s.stop < s.entry < s.target
        assert s.reason


def test_unknown_param_rejected():
    with pytest.raises(ValueError):
        STRATEGIES["ema_pullback"](not_a_param=1)


def test_higher_tf_uses_only_closed_bars(ohlcv):
    htf_close = ta.higher_tf(ohlcv, "1h", lambda h: h["Close"])
    # The 5m bar opening at 00:50 closes at 00:55, before the first hourly bar closes (01:00): no value yet.
    assert np.isnan(htf_close.loc["2026-01-01 00:50"])
    # The bar opening at 00:55 closes at 01:00 and may see the 00:00-01:00 hourly close, which is its own close.
    assert htf_close.loc["2026-01-01 00:55"] == ohlcv.loc["2026-01-01 00:55", "Close"]


def test_rsi_bounds(ohlcv):
    r = ta.rsi(ohlcv["Close"]).dropna()
    assert r.between(0, 100).all()


@pytest.mark.parametrize("name", ["squeeze_breakout", "ema_pullback", "vwap_reversion"])
@pytest.mark.parametrize("signal_tf", ["15min", "1h"])
def test_signal_timeframe_has_no_lookahead_and_fires_only_on_its_closes(name, signal_tf, ohlcv):
    strat = STRATEGIES[name](signal_tf=signal_tf, **{k: v for k, v in LOOSE[name].items() if k != "signal_tf"})
    full = strat.prepare(ohlcv)
    for cut in (1501, 2777, 3999):  # cuts in the middle of a forming 15m / 1h bar
        part = strat.prepare(ohlcv.iloc[:cut])
        pd.testing.assert_frame_equal(part, full.iloc[:cut], check_freq=False, rtol=1e-9, atol=1e-6)
    period = pd.Timedelta(signal_tf)
    closes = full.index[full["signal_bar"]] + (ohlcv.index[1] - ohlcv.index[0])
    assert ((closes - closes.normalize()) % period == pd.Timedelta(0)).all()
    signal_rows = [i for i in range(len(full)) if strat.entry_signal(full, i)]
    assert all(full["signal_bar"].iloc[i] for i in signal_rows)


def test_signal_timeframe_values_match_resampled_bars(ohlcv):
    strat = STRATEGIES["squeeze_breakout"](signal_tf="1h")
    ind = strat.prepare(ohlcv)
    hourly = ohlcv.resample("1h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    # The 5m bar opening at 01:55 closes the 01:00-02:00 hourly bar and must carry exactly its OHLCV
    row = ind.loc["2026-01-01 01:55"]
    assert row["signal_bar"]
    for c in ("Open", "High", "Low", "Close", "Volume"):
        assert row[c] == pytest.approx(hourly.loc["2026-01-01 01:00", c])
    assert row["prev:Close"] == pytest.approx(hourly.loc["2026-01-01 00:00", "Close"])
    assert not ind.loc["2026-01-01 02:00", "signal_bar"]


def test_binance_style_timeframes_are_normalised():
    s = STRATEGIES["ema_pullback"](signal_tf="15m", atr_tf="1d")
    assert s.p["signal_tf"] == "15min" and s.p["atr_tf"] == "1D" and s.p["htf"] == "1h"


def _orb_range_start(ohlcv_like, **params):
    s = STRATEGIES["opening_range"](atr_tf=None, **params)
    ind = s.prepare(ohlcv_like)
    first_valid = ind["or_high"].dropna().index[0]
    return first_valid + (ohlcv_like.index[1] - ohlcv_like.index[0])  # close time of first bar after the range


@pytest.mark.parametrize("start, expected_open_utc", [
    ("2026-01-05", "14:30"),  # EST (winter): 09:30 New York = 14:30 UTC
    ("2026-07-06", "13:30"),  # EDT (summer): 09:30 New York = 13:30 UTC
])
def test_opening_range_follows_new_york_time(ohlcv, start, expected_open_utc):
    df = ohlcv.copy()
    df.index = pd.date_range(start, periods=len(df), freq="5min", tz="UTC")
    complete = _orb_range_start(df, range_minutes=30)
    hh, mm = map(int, expected_open_utc.split(":"))
    assert complete == pd.Timestamp(start, tz="UTC") + pd.Timedelta(hours=hh, minutes=mm + 30 + 5)


def test_opening_range_utc_override(ohlcv):
    complete = _orb_range_start(ohlcv, session_tz="UTC", session_open="13:30", range_minutes=30)
    assert complete == pd.Timestamp("2026-01-01 14:05", tz="UTC")
