import numpy as np
import pandas as pd
import pytest

import indicators as ta
from backtester import run_backtest
from risk import RiskManager, position_size
from strategies import STRATEGIES


def test_position_size_with_notional_fraction_ignores_stop_distance():
    # 40% notional regardless of the stop, and still capped by max_position_pct
    assert position_size(10_000, 100, 99, 0.005, 1.0, notional_frac=0.4) == pytest.approx(40)
    assert position_size(10_000, 100, 50, 0.005, 1.0, notional_frac=0.4) == pytest.approx(40)
    assert position_size(10_000, 100, 99, 0.005, 0.25, notional_frac=0.4) == pytest.approx(25)
    assert position_size(10_000, 100, 99, 0.005, 1.0, notional_frac=-1) == 0
    assert RiskManager(max_position_pct=1.0).size(10_000, 100, 99, 0.4) == pytest.approx(40)


def test_realized_vol_is_annualised():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2026-01-01", periods=5000, freq="1h", tz="UTC")
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), index=idx)
    rv = ta.realized_vol(close, 1000, pd.Timedelta("1h"))
    assert rv.iloc[:1000].isna().all()
    assert rv.iloc[-1] == pytest.approx(0.01 * np.sqrt(8760), rel=0.1)


def test_signals_carry_vol_target_fraction(ohlcv):
    strat = STRATEGIES["donchian_ensemble"](lookbacks="12,24,48", signal_tf="15min", vol_target=0.3,
                                            vol_lookback=20, min_stop_fee_mult=0, min_target_fee_mult=0)
    ind = strat.prepare(ohlcv)
    sigs = [(i, s) for i in range(len(ind)) if (s := strat.entry_signal(ind, i))]
    assert sigs
    for i, s in sigs:
        assert s.size_frac == pytest.approx(0.3 / ind["rvol"].iloc[i])
    # off by default
    plain = STRATEGIES["donchian_ensemble"](lookbacks="12,24,48", signal_tf="15min")
    ind = plain.prepare(ohlcv)
    assert "rvol" not in ind
    assert all(s.size_frac is None for i in range(len(ind)) if (s := plain.entry_signal(ind, i)))


def test_backtest_sizes_by_vol_target(ohlcv):
    params = {"lookbacks": "12,24,48", "signal_tf": "15min", "vol_target": 0.3, "vol_lookback": 20,
              "min_stop_fee_mult": 0, "min_target_fee_mult": 0}
    from backtester import BacktestConfig
    cfg = BacktestConfig(risk_kwargs={"max_position_pct": 1.0})
    stats, _ = run_backtest(ohlcv, "donchian_ensemble", params, cfg)
    trades = stats["_trades"]
    assert len(trades)
    ind = STRATEGIES["donchian_ensemble"](**params).prepare(ohlcv)
    equity = stats["_equity_curve"]["Equity"]
    for _, t in trades.iterrows():
        sig_i = int(t["EntryBar"]) - 1  # signal on the bar before the fill
        expected = min(0.3 / ind["rvol"].iloc[sig_i], 0.9999)
        notional = abs(t["Size"]) * t["EntryPrice"]
        assert notional / equity.iloc[sig_i] == pytest.approx(expected, rel=0.02)
