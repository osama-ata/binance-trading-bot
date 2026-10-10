"""TODO §4.2: Probabilistic/Deflated Sharpe and PBO (CSCV)."""
import numpy as np
import pandas as pd
import pytest

from overfitting import (deflated_sharpe, expected_max_sharpe, pbo_cscv, period_returns,
                         probabilistic_sharpe, sharpe)

rng = np.random.default_rng(1)


def test_psr_extremes():
    assert probabilistic_sharpe(rng.normal(0.01, 0.01, 250)) > 0.99
    assert 0.2 < probabilistic_sharpe(rng.normal(0.0, 0.01, 250)) < 0.8
    assert probabilistic_sharpe(rng.normal(-0.01, 0.01, 250)) < 0.01


def test_expected_max_sharpe_grows_with_trials():
    few = expected_max_sharpe(rng.normal(0, 0.1, 5))
    many = expected_max_sharpe(rng.normal(0, 0.1, 500))
    assert 0 < few < many


def test_deflated_sharpe_is_stricter_than_psr():
    r = rng.normal(0.002, 0.01, 365)
    trials = rng.normal(0, 0.05, 27)
    assert deflated_sharpe(r, trials) < probabilistic_sharpe(r)


def test_pbo_is_about_half_for_pure_noise():
    noise = pd.DataFrame(rng.normal(0, 0.01, (400, 20)))
    res = pbo_cscv(noise, n_blocks=10)
    assert 0.25 < res["pbo"] < 0.75
    assert res["n_splits"] == res["n_splits_total"] == 252


def test_pbo_is_low_when_one_combo_has_real_edge():
    m = rng.normal(0, 0.01, (400, 20))
    m[:, 7] += 0.004  # genuine skill, present in every block
    res = pbo_cscv(pd.DataFrame(m), n_blocks=10)
    assert res["pbo"] < 0.1


def test_pbo_split_sampling():
    res = pbo_cscv(pd.DataFrame(rng.normal(0, 0.01, (320, 5))), n_blocks=16, max_splits=200)
    assert res["n_splits"] == 200 and res["n_splits_total"] == 12870


def test_sharpe_and_period_returns():
    assert sharpe(np.zeros(10)) == 0.0
    eq = pd.Series(np.linspace(100, 110, 49), index=pd.date_range("2026-01-01", periods=49, freq="12h"))
    r = period_returns(eq)
    assert len(r) == 24 and (r > 0).all()


def test_overfitting_report_on_grid(ohlcv):
    from backtester import overfitting_report, walk_forward

    folds, eq = walk_forward(ohlcv, "squeeze_breakout", 4, 2, grid={"rr": [2.0, 3.0]}, min_trades=1)
    rep = overfitting_report(ohlcv, "squeeze_breakout", eq, n_blocks=4)
    assert rep["n_trials"] == 27 and 0 <= rep["pbo"] <= 1
    assert "dsr" in rep
