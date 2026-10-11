import numpy as np
import pandas as pd
import pytest

import indicators as ta
from strategies import STRATEGIES


def _series(values, freq="1h"):
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values), freq=freq, tz="UTC"),
                     dtype=float)


def test_efficiency_ratio_trend_vs_chop():
    trend = _series(np.arange(100.0, 150.0))
    chop = _series([100.0, 101.0] * 25)
    assert ta.efficiency_ratio(trend, 10).iloc[-1] == pytest.approx(1.0)
    assert ta.efficiency_ratio(chop, 10).iloc[-1] == pytest.approx(0.0)
    assert ta.efficiency_ratio(trend, 10).iloc[:10].isna().all()


def test_choppiness_bounds():
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 500)))
    df = pd.DataFrame({"Open": c, "High": c * 1.002, "Low": c * 0.998, "Close": c},
                      index=pd.date_range("2026-01-01", periods=500, freq="1h", tz="UTC"))
    chop = ta.choppiness(df, 14).dropna()
    assert len(chop) and chop.between(0, 100).all()
    line = np.linspace(100, 200, 500)  # straight line: 14 true ranges vs a 13-step range -> CHOP near 0
    straight = pd.DataFrame({"Open": line, "High": line, "Low": line, "Close": line}, index=df.index)
    assert ta.choppiness(straight, 14).iloc[-1] < 5 < chop.median()


def test_vol_percentile_ranks_against_trailing_window():
    flip = np.where(np.arange(320) % 2 == 0, 1.0, -1.0)
    r = flip * np.r_[np.full(300, 0.001), np.full(20, 0.02)]  # constant quiet vol, then a growing spike
    close = _series(100 * np.exp(np.cumsum(r)))
    pct = ta.vol_percentile(close, 24, 200)
    assert pct.iloc[:223].isna().all() and pct.iloc[223:].notna().all()
    assert pct.iloc[-1] == pytest.approx(1.0)  # the spike is the highest vol in the window
    assert pct.iloc[250:300].max() < 0.75  # quiet bars tie, so they rank mid-pack
    assert pct.dropna().between(0, 1).all()


def test_filters_off_by_default_add_no_columns(ohlcv):
    s = STRATEGIES["squeeze_breakout"]()
    assert s._regime_filters() == []
    ind = s.prepare(ohlcv)
    assert not {"er", "chop", "rv_pct"} & set(ind.columns)


def test_regime_filter_blocks_entries_outside_band(ohlcv):
    base = STRATEGIES["squeeze_breakout"](min_stop_fee_mult=0, min_target_fee_mult=0, rv_pct_window=48)
    ind0 = base.prepare(ohlcv)
    sigs0 = {i for i in range(len(ind0)) if base.entry_signal(ind0, i)}
    filt = STRATEGIES["squeeze_breakout"](min_stop_fee_mult=0, min_target_fee_mult=0, rv_pct_window=48,
                                          er_min=0.2)
    ind = filt.prepare(ohlcv)
    sigs = {i for i in range(len(ind)) if filt.entry_signal(ind, i)}
    assert sigs0 and sigs < sigs0
    assert all(ind["er"].iloc[i] >= 0.2 for i in sigs)
    assert filt.rejected["regime filter"] > 0


@pytest.mark.parametrize("hours, allowed", [("13-17", {13, 14, 15, 16}), ("18-6", {18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5})])
def test_trade_hours_gate_uses_bar_close_time(ohlcv, hours, allowed):
    s = STRATEGIES["squeeze_breakout"](min_stop_fee_mult=0, min_target_fee_mult=0, trade_hours=hours)
    ind = s.prepare(ohlcv)
    bar = ind.index[1] - ind.index[0]
    hours_seen = {(ind.index[i] + bar).hour for i in range(len(ind)) if s.entry_signal(ind, i)}
    assert hours_seen and hours_seen <= allowed


def test_regime_warmup_covers_percentile_window():
    s = STRATEGIES["opening_range"](rv_pct_min=0.2, rv_pct_window=720, rv_n=24)
    assert s.warmup_bars(pd.Timedelta("5min")) >= (720 + 24 + 1) * 12
