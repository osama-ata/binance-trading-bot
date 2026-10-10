"""TODO §1 acceptance: fee hurdle gates, fee-adjusted break-even, cost metrics."""
import numpy as np
import pandas as pd
import pytest

import indicators as ta
from backtester import BacktestConfig, run_backtest, summarize
from brokers import PaperBroker, Store
from risk import Position, breakeven_level, updated_stop
from strategies import STRATEGIES, BaseStrategy, Signal

FEE = 0.001


class FixedStop(BaseStrategy):
    """Enters once at `entry_at`, stop `stop_pct` below the close, target far away."""

    name = "fixed_stop"
    defaults = {"stop_pct": 0.01, "rr": 10.0, "breakeven_at_r": 1.0, "max_bars": 1000, "atr_tf": None,
                "entry_at": 29}

    def indicator_warmup(self, bar) -> int:
        return 20

    def indicators(self, df):
        return {"bar_no": pd.Series(np.arange(len(df), dtype=float), index=df.index)}

    def entry(self, row, prev):
        return "fixed" if row["bar_no"] == self.p["entry_at"] else None

    def stop_for(self, row):
        return row["Close"] * (1 - self.p["stop_pct"])


def _row_frame(stop_pct: float) -> tuple[FixedStop, pd.DataFrame]:
    idx = pd.date_range("2026-01-01", periods=40, freq="5min", tz="UTC")
    df = pd.DataFrame({"Open": 100.0, "High": 100.1, "Low": 99.9, "Close": 100.0, "Volume": 1.0}, index=idx)
    s = FixedStop(fee_rate=FEE, stop_pct=stop_pct)
    return s, s.prepare(df)


def test_signal_rejected_when_stop_inside_fee_hurdle():
    # 4 round trips at 0.1%/side = 0.8%: a 0.5% stop is rejected, a 1% stop passes
    s, ind = _row_frame(0.005)
    assert s.entry_signal(ind, 29) is None
    assert s.rejected["stop below fee hurdle"] == 1
    s, ind = _row_frame(0.01)
    assert s.entry_signal(ind, 29) is not None


def test_signal_rejected_when_target_inside_fee_hurdle():
    s, ind = _row_frame(0.01)
    s.p["rr"] = 0.5  # 0.5% target < 5 round trips (1%)
    assert s.entry_signal(ind, 29) is None
    assert s.rejected["target below fee hurdle"] == 1


def test_low_volatility_gate():
    s, ind = _row_frame(0.01)
    s.p["min_atr_pct"] = 0.01  # synthetic ATR is ~0.2%
    assert s.entry_signal(ind, 29) is None
    assert s.rejected["low volatility"] == 1


def test_breakeven_level_covers_fees_and_slippage():
    entry, fee, slip = 100.0, 0.001, 0.0005
    level = breakeven_level(entry, fee, slip)
    exit_px = level * (1 - slip)
    pnl = (exit_px - entry) - fee * entry - fee * exit_px
    assert pnl == pytest.approx(0, abs=1e-12)
    assert breakeven_level(entry, fee, slip, tick=0.01) == pytest.approx(level + 0.01)


def test_breakeven_never_lowers_stop():
    pos = Position("X", 1, entry=100, stop=100.5, target=110, initial_stop=99, opened_at=None, strategy="t")
    assert updated_stop(pos, bar_high=105, breakeven_at_r=1.0, fee_rate=FEE) == 100.5


def test_paper_breakeven_exit_is_not_a_loss():
    b = PaperBroker(Store(None, "VIRTUAL"), cash=10_000, fee_rate=FEE, slippage_bps=5)
    pos = b.open("BTCUSDT", 10, Signal(entry=100.0, stop=99.0, target=110.0, reason="t"), "t", None)
    new_stop = updated_stop(pos, bar_high=pos.entry + pos.initial_risk, breakeven_at_r=1.0,
                            fee_rate=FEE, slippage=b.slip, tick=0.01)
    b.move_stop("BTCUSDT", new_stop)
    pnl = b.check_exits("BTCUSDT", {"Open": 101.0, "High": 101.0, "Low": 99.5, "Close": 99.6}, None)
    assert pnl > 0  # exactly 0 + one tick of profit


def test_backtest_breakeven_exit_is_not_a_loss():
    # Flat at 100, enter at bar 30's open, rally +1.5R, then collapse through the entry.
    idx = pd.date_range("2026-01-01", periods=40, freq="5min", tz="UTC")
    df = pd.DataFrame({"Open": 100.0, "High": 100.1, "Low": 99.9, "Close": 100.0, "Volume": 1.0}, index=idx)
    df.iloc[30] = [100.0, 101.6, 99.95, 101.4, 1.0]
    df.iloc[31] = [101.4, 101.5, 101.2, 101.3, 1.0]
    df.iloc[32] = [101.3, 101.3, 97.5, 98.0, 1.0]  # trades down through the break-even stop (no gap)
    df.iloc[33:] = [[98.0, 98.2, 97.8, 98.0, 1.0]] * 7
    stats, _ = run_backtest(df, FixedStop, {"stop_pct": 0.01}, BacktestConfig(commission=FEE, slippage_bps=5))
    trades = stats["_trades"]
    assert len(trades) == 1
    assert trades["PnL"].iloc[0] >= 0
    assert trades["ExitPrice"].iloc[0] < trades["EntryPrice"].iloc[0] * 1.01


def test_summarize_reports_cost_metrics(ohlcv):
    stats, _ = run_backtest(ohlcv, "squeeze_breakout", cfg=BacktestConfig(commission=FEE))
    m = summarize(stats)
    for key in ("Fees [R]", "Gross Avg R", "Effective risk [%]", "Cap-bound trades [%]"):
        assert key in m
    if m["# Trades"]:
        assert m["Fees [R]"] > 0
        assert m["Gross Avg R"] == pytest.approx(m["Avg R"] + m["Fees [R]"])


def test_stops_use_higher_timeframe_atr(ohlcv):
    s = STRATEGIES["squeeze_breakout"]()
    ind = s.prepare(ohlcv)
    expected = ta.higher_tf(ohlcv, "1h", lambda h: ta.atr(h, s.p["atr_n"]))
    pd.testing.assert_series_equal(ind["atr"], expected, check_names=False)
    assert ind["atr"].median() > 2 * ind["atr_base"].median()
