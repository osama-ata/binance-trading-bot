import pandas as pd
import pytest

from backtester import BacktestConfig, run_backtest, summarize, walk_forward
from binance_client import klines_to_df
from strategies import STRATEGIES


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_backtest_runs_long_only(name, ohlcv):
    stats, _ = run_backtest(ohlcv, name)
    trades = stats["_trades"]
    assert (trades["Size"] > 0).all()  # spot: never short
    m = summarize(stats)
    assert m["# Trades"] == len(trades)


def test_costs_reduce_returns(ohlcv):
    free, _ = run_backtest(ohlcv, "squeeze_breakout", cfg=BacktestConfig(commission=0, slippage_bps=0))
    costly, _ = run_backtest(ohlcv, "squeeze_breakout", cfg=BacktestConfig(commission=0.001, slippage_bps=5))
    assert len(free["_trades"]) > 0
    assert costly["Equity Final [$]"] < free["Equity Final [$]"]


def test_walk_forward_only_trades_out_of_sample(ohlcv):
    folds, equity = walk_forward(
        ohlcv, "squeeze_breakout", train_days=4, test_days=2, grid={"rr": [2.0, 3.0]}, min_trades=1
    )
    assert len(folds) >= 1
    assert equity.index[0] >= folds["test_start"].iloc[0]


def test_klines_to_df_handles_ms_and_us():
    ms = [[1791417600000, "1", "2", "0.5", "1.5", "10"]]
    us = [[1791417600000000, "1", "2", "0.5", "1.5", "10"]]
    assert klines_to_df(ms).index[0] == klines_to_df(us).index[0] == pd.Timestamp(1791417600000, unit="ms", tz="UTC")
