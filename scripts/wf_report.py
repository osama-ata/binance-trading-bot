"""Walk-forward report for every strategy × symbol × interval, printed as a Markdown table.

Usage: uv run python scripts/wf_report.py [--start 2026-04-01] [--intervals 5m,15m] [--symbols BTCUSDT,ETHUSDT]
                                          [--set signal_tf=1h] [--risk max_position_pct=1.0] [--jobs 6]
Only out-of-sample (test-window) results are reported. Runs are spread over `--jobs` processes.
Every run is cached in data/research/ (see src/research_cache.py): rerunning identical inputs on unchanged code
is instant; --refresh forces a recompute; --out saves the table (commit it under reports/ to keep it).
DSR = Deflated Sharpe of the stitched out-of-sample daily returns, deflated for the size of the parameter
grid (>0.95 = unlikely to be luck). PBO = probability of backtest overfitting from CSCV over the full-period
grid (>=0.5 = picking the in-sample best is no better than chance). B&H Sharpe = annualised Sharpe of buying and
holding over the same out-of-sample window, the bar a long-only strategy has to beat on a risk-adjusted basis.
"""
import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backtester import BacktestConfig, overfitting_report, walk_forward  # noqa: E402
import research_cache  # noqa: E402
from data import load_klines  # noqa: E402
from overfitting import period_returns, sharpe  # noqa: E402
from strategies import STRATEGIES, BaseStrategy  # noqa: E402


def parse_kv(pairs: list[str]) -> dict:
    out = {}
    for kv in pairs:
        k, v = kv.split("=", 1)
        try:
            out[k] = float(v) if "." in v else int(v)
        except ValueError:
            out[k] = None if v.lower() == "none" else v
    return out


def run_one(name: str, symbol: str, interval: str, args: argparse.Namespace, fixed: dict,
            risk: dict) -> tuple[tuple, str]:
    t0 = time.time()
    params = {k: v for k, v in fixed.items() if k in {**BaseStrategy.defaults, **STRATEGIES[name].defaults}}
    spec = {
        "kind": "walk_forward", "strategy": name, "symbol": symbol, "interval": interval,
        "start": args.start, "end": args.end, "train_days": args.train_days, "test_days": args.test_days,
        "min_trades": args.min_trades, "fee": args.fee, "slippage_bps": args.slippage_bps, "params": params,
        "grid": STRATEGIES[name].param_grid, "overfit": not args.no_overfit,
    }
    if risk:  # only added when set, so default runs keep their cache keys
        spec["risk"] = risk
    key = research_cache.run_key(spec)
    cached = None if args.refresh else research_cache.load(key)
    if cached:
        summary = cached["summary"]
        print(f"  {name} {symbol} {interval}: cached ({key})", file=sys.stderr, flush=True)
    else:
        df = load_klines(symbol, interval, args.start, args.end)
        cfg = BacktestConfig(10_000, args.fee, args.slippage_bps, risk or None)
        folds, eq = walk_forward(df, name, args.train_days, args.test_days, cfg=cfg, min_trades=args.min_trades,
                                 params=params)
        summary = {"signal_tf": params.get("signal_tf", STRATEGIES[name].defaults.get("signal_tf")) or interval,
                   "folds": len(folds), "oos_trades": int(folds["test_trades"].sum()) if len(folds) else 0}
        if not eq.empty:
            px = df["Close"][(df.index >= eq.index[0]) & (df.index <= eq.index[-1])]
            summary.update({
                "oos_return_pct": float((eq.iloc[-1] / eq.iloc[0] - 1) * 100),
                "buy_hold_pct": float((px.iloc[-1] / px.iloc[0] - 1) * 100),
                "oos_max_dd_pct": float(((eq / eq.cummax()) - 1).min() * 100),
                "buy_hold_sharpe_ann": float(sharpe(period_returns(px)) * np.sqrt(365)),
            })
            if not args.no_overfit:
                summary.update(overfitting_report(df, name, eq, cfg, params))
        summary["seconds"] = round(time.time() - t0, 1)
        research_cache.save(key, spec, summary, folds, eq)
        print(f"  {name} {symbol} {interval}: {time.time() - t0:.0f}s ({key})", file=sys.stderr, flush=True)

    def f(k: str) -> str:
        v = summary.get(k)
        return "n/a" if v is None or v != v else f"{v:.2f}"

    return (interval, symbol, name), (
        f"| {name} | {symbol} | {interval} | {summary['signal_tf']} | {f('oos_return_pct')} | {f('buy_hold_pct')} | "
        f"{f('oos_max_dd_pct')} | {summary['oos_trades']} | {summary['folds']} | {f('oos_sharpe_ann')} | "
        f"{f('buy_hold_sharpe_ann')} | {f('dsr')} | {f('pbo')} |")


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
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--no-overfit", action="store_true", help="skip the PBO / Deflated Sharpe columns")
    ap.add_argument("--refresh", action="store_true", help="recompute even if a cached result exists")
    ap.add_argument("--out", help="also write the Markdown report to this file (e.g. reports/phase1.md)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="fixed strategy param for every run, e.g. --set signal_tf=1h (repeatable)")
    ap.add_argument("--risk", action="append", default=[], metavar="KEY=VALUE",
                    help="RiskManager setting for every run, e.g. --risk max_position_pct=1.0 (repeatable)")
    args = ap.parse_args()
    fixed, risk = parse_kv(args.set), parse_kv(args.risk)

    intervals, symbols, names = args.intervals.split(","), args.symbols.split(","), args.strategies.split(",")
    for interval in intervals:  # download/cache once, before forking
        for symbol in symbols:
            load_klines(symbol, interval, args.start, args.end)

    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_one, n, s, i, args, fixed, risk) for i in intervals for s in symbols for n in names]
        rows = dict(f.result() for f in as_completed(futures))

    lines = [
        f"Walk-forward {args.start} → {args.end}, train {args.train_days}d / test {args.test_days}d, "
        f"fee {args.fee:.4%}/side, slippage {args.slippage_bps} bps/side, min train trades {args.min_trades}"
        f"{', fixed params ' + str(fixed) if fixed else ''}{', risk ' + str(risk) if risk else ''} (code {research_cache.code_fingerprint()})",
        "",
        "| Strategy | Symbol | Bars | Signal TF | OOS return % | Buy & hold % | OOS max DD % | OOS trades | Folds "
        "| OOS Sharpe (ann.) | B&H Sharpe | DSR | PBO |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *[rows[(i, s, n)] for i in intervals for s in symbols for n in names],
    ]
    print("\n".join(lines))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
