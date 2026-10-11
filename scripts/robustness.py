"""Phase 1c: robustness of the 4h Donchian ensemble with parameters fixed in advance (no optimiser).

Usage: uv run python scripts/robustness.py [--jobs 16] [--out reports/phase1c/donchian_4h_robustness.md]

Design (pre-registered in TODO.md before the first run):
  - donchian_ensemble, 4h signals on 1h execution bars, the strategy defaults (entry 0.6 / exit 0.2 / stop 3 ATR /
    lookbacks 24..384), vol targeting 30% over 180 signal bars, max_position_pct 1.0, time stop off.
  - BTC, ETH, SOL, BNB; history from 2020-01-01 (or listing) for warm-up; every symbol is evaluated on the same
    window EVAL_START → EVAL_END.
  - Primary result: equal-weight portfolio of the four symbols (daily-rebalanced average of daily returns).
  - Stress: one-at-a-time parameter sweep at 50/75/125/150% (lookbacks at 0.5x/2x) = 15 variants incl. base;
    costs at 2x and 3x slippage and a 0.15% fee; year-by-year returns.
  - Gate: portfolio DSR > 0.95 (deflated over the 15 variants) and PBO < 0.5 (CSCV over the 15 portfolio return
    series), positive in a majority of calendar years, Sharpe > 0 for every sweep variant and at 2x slippage.
Every backtest is cached in data/research/ (kind "fixed_backtest").
"""
import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import research_cache  # noqa: E402
from backtester import BacktestConfig, run_backtest  # noqa: E402
from data import load_klines  # noqa: E402
from overfitting import deflated_sharpe, pbo_cscv, period_returns, sharpe  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
HISTORY_START, EVAL_START, EVAL_END = "2020-01-01", "2021-06-01", "2026-10-09"
INTERVAL, FEE, SLIPPAGE_BPS = "1h", 0.001, 2.0
RISK = {"max_position_pct": 1.0}
BASE = {"signal_tf": "4h", "max_bars": 100000, "vol_target": 0.3, "vol_lookback": 180}
DEFAULTS = {"stop_atr": 3.0, "entry_threshold": 0.6, "exit_threshold": 0.2, "lookbacks": "24,48,96,192,384"}
SWEEP = {
    "stop_atr": [1.5, 2.25, 3.75, 4.5],
    "entry_threshold": [0.4, 0.5, 0.7, 0.8],
    "exit_threshold": [0.0, 0.1, 0.3, 0.4],
    "lookbacks": ["12,24,48,96,192", "48,96,192,384,768"],
}
COST_STRESS = {"slippage 2x": (FEE, 2 * SLIPPAGE_BPS), "slippage 3x": (FEE, 3 * SLIPPAGE_BPS),
               "fee 0.15%": (0.0015, SLIPPAGE_BPS)}
ANN = np.sqrt(365)


def variants() -> dict[str, dict]:
    out = {"base": {}}
    for k, values in SWEEP.items():
        for v in values:
            out[f"{k}={v}"] = {k: v}
    return out


def run(symbol: str, params: dict, fee: float, slippage_bps: float) -> tuple[pd.Series, dict]:
    """Daily equity over the evaluation window for one fixed-parameter backtest (cached)."""
    spec = {"kind": "fixed_backtest", "strategy": "donchian_ensemble", "symbol": symbol, "interval": INTERVAL,
            "start": HISTORY_START, "trade_from": EVAL_START, "end": EVAL_END, "fee": fee,
            "slippage_bps": slippage_bps, "params": {**BASE, **params}, "risk": RISK}
    key = research_cache.run_key(spec)
    cached = research_cache.load(key)
    if cached:
        return cached["equity"], cached["summary"]
    t0 = time.time()
    df = load_klines(symbol, INTERVAL, HISTORY_START, EVAL_END)
    stats, _ = run_backtest(df, "donchian_ensemble", {**BASE, **params}, BacktestConfig(10_000, fee, slippage_bps, RISK),
                            trade_from=pd.Timestamp(EVAL_START, tz="UTC"))
    eq = stats["_equity_curve"]["Equity"]
    eq = eq[eq.index >= pd.Timestamp(EVAL_START, tz="UTC")].resample("1D").last().ffill()
    px = df["Close"][df.index >= pd.Timestamp(EVAL_START, tz="UTC")].resample("1D").last().ffill()
    r, bh = period_returns(eq), period_returns(px)
    summary = {
        "signal_tf": BASE["signal_tf"], "oos_trades": int(len(stats["_trades"])), "folds": 0,
        "oos_return_pct": float((eq.iloc[-1] / eq.iloc[0] - 1) * 100),
        "buy_hold_pct": float((px.iloc[-1] / px.iloc[0] - 1) * 100),
        "oos_max_dd_pct": float(((eq / eq.cummax()) - 1).min() * 100),
        "oos_sharpe_ann": float(sharpe(r) * ANN), "buy_hold_sharpe_ann": float(sharpe(bh) * ANN),
        "exposure_pct": float(stats["Exposure Time [%]"]), "seconds": round(time.time() - t0, 1),
    }
    research_cache.save(key, spec, summary, None, eq)
    return eq, summary


def job(args):
    name, symbol, params, fee, slip = args
    eq, summary = run(symbol, params, fee, slip)
    return name, symbol, eq, summary


def fmt(v, d=2):
    return "n/a" if v is None or v != v else f"{v:.{d}f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--out", default="reports/phase1c/donchian_4h_robustness.md")
    a = ap.parse_args()

    for s in SYMBOLS:  # download/cache once, before forking
        load_klines(s, INTERVAL, HISTORY_START, EVAL_END)
    tasks = [(n, s, p, FEE, SLIPPAGE_BPS) for n, p in variants().items() for s in SYMBOLS]
    tasks += [(n, s, {}, fee, slip) for n, (fee, slip) in COST_STRESS.items() for s in SYMBOLS]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        results = list(pool.map(job, tasks))
    eqs = {(n, s): eq for n, s, eq, _ in results}
    sums = {(n, s): sm for n, s, _, sm in results}

    def portfolio(name: str) -> pd.Series:
        rets = pd.concat({s: period_returns(eqs[(name, s)]) for s in SYMBOLS}, axis=1).dropna()
        return rets.mean(axis=1)

    px = {s: load_klines(s, "1d", EVAL_START, EVAL_END)["Close"] for s in SYMBOLS}
    bh_port = pd.concat({s: px[s].pct_change() for s in SYMBOLS}, axis=1).dropna().mean(axis=1)

    names = list(variants())
    port = pd.DataFrame({n: portfolio(n) for n in names}).dropna()
    srs = {n: sharpe(port[n]) for n in names}
    base = port["base"]
    dsr = deflated_sharpe(base, list(srs.values()))
    pbo = pbo_cscv(port, n_blocks=16)
    bh_aligned = bh_port.reindex(base.index).fillna(0.0)

    def stats_row(label, r):
        eq = (1 + r).cumprod()
        cagr = eq.iloc[-1] ** (365 / len(r)) - 1
        dd = (eq / eq.cummax() - 1).min()
        row = f"| {label} | {fmt(cagr * 100)} | {fmt(r.std() * ANN * 100)} | {fmt(sharpe(r) * ANN)} | {fmt(dd * 100)} |"
        return row

    lines = [
        f"# Phase 1c: 4h Donchian robustness (fixed parameters, no optimiser)",
        "",
        f"Evaluation {EVAL_START} → {EVAL_END} on {INTERVAL} bars (history from {HISTORY_START} for warm-up), "
        f"fee {FEE:.2%}/side, slippage {SLIPPAGE_BPS} bps/side, params {BASE} + defaults {DEFAULTS}, "
        f"risk {RISK} (code {research_cache.code_fingerprint()}).",
        "",
        "## Per symbol (base parameters)",
        "",
        "| Symbol | Return % | B&H % | Max DD % | Trades | Exposure % | Sharpe | B&H Sharpe |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in SYMBOLS:
        m = sums[("base", s)]
        lines.append(f"| {s} | {fmt(m['oos_return_pct'])} | {fmt(m['buy_hold_pct'])} | {fmt(m['oos_max_dd_pct'])} | "
                     f"{m['oos_trades']} | {fmt(m['exposure_pct'], 0)} | {fmt(m['oos_sharpe_ann'])} | "
                     f"{fmt(m['buy_hold_sharpe_ann'])} |")

    lines += ["", "## Equal-weight portfolio (daily rebalanced)", "",
              "| Series | CAGR % | Vol % | Sharpe | Max DD % |", "|---|---|---|---|---|",
              stats_row("Donchian portfolio (base)", base),
              stats_row("Buy & hold basket", bh_aligned),
              "", f"- **DSR {fmt(dsr)}** (deflated over {len(names)} variants), **PBO {fmt(pbo['pbo'])}** "
              f"(CSCV, {pbo['n_splits']} splits over the {len(names)} portfolio variants).", ""]

    years = sorted(set(base.index.year))
    lines += ["## Year by year (portfolio)", "", "| Year | Donchian % | B&H basket % |", "|---|---|---|"]
    pos_years = 0
    for y in years:
        d, b = base[base.index.year == y], bh_aligned[bh_aligned.index.year == y]
        dy, by = ((1 + d).prod() - 1) * 100, ((1 + b).prod() - 1) * 100
        pos_years += dy > 0
        lines.append(f"| {y}{' (part)' if y in (years[0], years[-1]) else ''} | {fmt(dy)} | {fmt(by)} |")

    lines += ["", "## Parameter sensitivity (portfolio Sharpe; per-symbol Sharpe)", "",
              f"| Variant | Portfolio Sharpe | {' | '.join(SYMBOLS)} |", "|---|---|" + "---|" * len(SYMBOLS)]
    for n in names:
        per = " | ".join(fmt(sums[(n, s)]["oos_sharpe_ann"]) for s in SYMBOLS)
        lines.append(f"| {n} | {fmt(srs[n] * ANN)} | {per} |")

    lines += ["", "## Cost stress (portfolio)", "", "| Costs | Sharpe | CAGR % |", "|---|---|---|",
              f"| base (0.1% fee, {SLIPPAGE_BPS} bps) | {fmt(srs['base'] * ANN)} | "
              f"{fmt(((1 + base).prod() ** (365 / len(base)) - 1) * 100)} |"]
    cost_sr = {}
    for n in COST_STRESS:
        r = portfolio(n)
        cost_sr[n] = sharpe(r) * ANN
        lines.append(f"| {n} | {fmt(cost_sr[n])} | {fmt(((1 + r).prod() ** (365 / len(r)) - 1) * 100)} |")

    checks = {
        "DSR > 0.95": dsr > 0.95,
        "PBO < 0.5": pbo["pbo"] < 0.5,
        f"positive in a majority of years ({pos_years}/{len(years)})": pos_years > len(years) / 2,
        "Sharpe > 0 for every sweep variant": min(srs.values()) > 0,
        "Sharpe > 0 at 2x slippage": cost_sr["slippage 2x"] > 0,
    }
    lines += ["", "## Gate", "", *[f"- [{'x' if ok else ' '}] {k}" for k, ok in checks.items()], "",
              f"**{'PASS' if all(checks.values()) else 'FAIL'}**"]
    text = "\n".join(lines) + "\n"
    print(text)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text)
    # Daily series for the residual-edge check
    pd.DataFrame({"strategy_return": base, "buy_hold_basket_return": bh_aligned}).to_csv(
        Path(a.out).with_suffix(".daily.csv"), index_label="date", date_format="%Y-%m-%d")


if __name__ == "__main__":
    main()
