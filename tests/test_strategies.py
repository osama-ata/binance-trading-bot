import numpy as np
import pandas as pd
import pytest

import indicators as ta
from strategies import STRATEGIES


# Loosened params so every strategy fires on the synthetic series
LOOSE = {
    "ema_pullback": {"htf_fast": 10, "htf_slow": 30, "adx_min": 0, "rsi_low": 50},
    "vwap_reversion": {"band_k": 1.0, "rsi_max": 50, "adx_max": 100, "min_reward_pct": 0.0},
    "squeeze_breakout": {},
    "opening_range": {},
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
