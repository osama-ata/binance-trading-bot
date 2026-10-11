"""TODO §4.1: look-ahead (truncated-history) and recursive (warm-up) analysis for every strategy."""
import numpy as np
import pandas as pd
import pytest

from strategies import STRATEGIES
from validation import default_cuts, lookahead_check, recursive_check

pytestmark = pytest.mark.slow

# Loosened so every strategy fires on the synthetic data (signal bars are always among the cuts)
LOOSE = {
    "ema_pullback": {"htf_fast": 10, "htf_slow": 30, "adx_min": 0, "rsi_low": 50},
    "vwap_reversion": {"band_k": 1.0, "rsi_max": 50, "adx_max": 100},
    "squeeze_breakout": {},
    "opening_range": {},
    "donchian_ensemble": {"lookbacks": "12,24,48", "signal_tf": "15min"},
}
VARIANTS = [(name, {}) for name in STRATEGIES] + [
    ("squeeze_breakout", {"signal_tf": "1h"}),
    ("vwap_reversion", {"signal_tf": "15min"}),
    ("ema_pullback", {"signal_tf": "15min"}),
    ("donchian_ensemble", {"signal_tf": "1h", "vol_target": 0.3, "vol_lookback": 20}),
]


@pytest.mark.parametrize("name, extra", VARIANTS, ids=[f"{n}-{e.get('signal_tf', 'base')}{'-vt' if 'vol_target' in e else ''}" for n, e in VARIANTS])
def test_no_lookahead_at_200_cut_points(name, extra, ohlcv):
    strat = STRATEGIES[name](**{**LOOSE[name], **extra})
    cuts = default_cuts(strat, ohlcv, n=200)
    assert len(cuts) >= 150
    problems = lookahead_check(strat, ohlcv, cuts)
    assert not problems, problems[:3]


def test_lookahead_check_catches_a_leak(ohlcv):
    """Sanity check of the checker itself: a centred rolling mean peeks two bars ahead."""

    class Leaky(STRATEGIES["squeeze_breakout"]):
        def indicators(self, df):
            out = super().indicators(df)
            out["future"] = df["Close"].rolling(5, center=True).mean()
            return out

    s = Leaky()
    assert lookahead_check(s, ohlcv, [1000, 2000, 3000])


@pytest.fixture(scope="module")
def long_ohlcv() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = 20_000
    close = 30_000 * np.exp(np.cumsum(rng.normal(0.00002, 0.003, n)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.002, n)) * close
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"Open": open_, "High": np.maximum(open_, close) + spread,
                         "Low": np.minimum(open_, close) - spread, "Close": close,
                         "Volume": rng.lognormal(3, 0.6, n)}, index=idx)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_warmup_is_long_enough_for_live_engine(name, long_ohlcv):
    """With the history the live engine keeps (warmup_bars + 50), indicators match full history within 0.1%."""
    strat = STRATEGIES[name]()
    n = strat.warmup_bars(pd.Timedelta("5min")) + 50
    assert n < len(long_ohlcv) // 2, "fixture too short for this strategy's warm-up"
    rec = recursive_check(strat, long_ohlcv, [n], eval_points=8)
    assert rec.loc[n, "max"] < 1e-3, rec.loc[n][rec.loc[n] >= 1e-3].to_dict()


def test_short_history_is_detected(long_ohlcv):
    """Sanity check: 40 bars is far too short for EMA200-on-1h, and the check must say so."""
    rec = recursive_check(STRATEGIES["ema_pullback"](), long_ohlcv, [40, 5000], eval_points=4)
    assert rec.loc[40, "max"] > 1e-3 > rec.loc[5000, "max"]
