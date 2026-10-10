"""Walk-forward report for every strategy × symbol × interval, printed as a Markdown table.

Usage: uv run python scripts/wf_report.py [--start 2026-04-01] [--intervals 5m,15m] [--symbols BTCUSDT,ETHUSDT]
Only out-of-sample (test-window) results are reported.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backtester import BacktestConfig, walk_forward  # noqa: E402
from data import load_klines  # noqa: E402
from strategies import STRATEGIES  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-01")
    ap.add_argument("--end", default="2026-10-09")
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--intervals", default="5m,15m")
    ap.add_argument("--strategies", default=",".join(STRATEGIES))
    ap.add_argument("--train-days", type=int, default=30)
    ap.add_argument("--test-days", type=int, default=7)
    ap.add_argument("--min-trades", type=int, default=10)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slippage-bps", type=float, default=2.0)
    args = ap.parse_args()

    print(f"Walk-forward {args.start} → {args.end}, train {args.train_days}d / test {args.test_days}d, "
          f"fee {args.fee:.4%}/side, slippage {args.slippage_bps} bps, min train trades {args.min_trades}\n")
    print("| Strategy | Symbol | TF | OOS return % | Buy & hold % | OOS max DD % | OOS trades | Folds |")
    print("|---|---|---|---|---|---|---|---|")
    for interval in args.intervals.split(","):
        for symbol in args.symbols.split(","):
            df = load_klines(symbol, interval, args.start, args.end)
            for name in args.strategies.split(","):
                t0 = time.time()
                folds, eq = walk_forward(
                    df, name, args.train_days, args.test_days,
                    cfg=BacktestConfig(10_000, args.fee, args.slippage_bps), min_trades=args.min_trades,
                )
                if eq.empty:
                    print(f"| {name} | {symbol} | {interval} | n/a | n/a | n/a | 0 | 0 |", flush=True)
                    continue
                ret = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
                dd = ((eq / eq.cummax()) - 1).min() * 100
                px = df["Close"][(df.index >= eq.index[0]) & (df.index <= eq.index[-1])]
                bh = (px.iloc[-1] / px.iloc[0] - 1) * 100
                print(f"| {name} | {symbol} | {interval} | {ret:.2f} | {bh:.2f} | {dd:.2f} | "
                      f"{int(folds['test_trades'].sum())} | {len(folds)} |", flush=True)
                print(f"  ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
