"""Build inputs for tradermonty/claude-trading-skills' residual-edge-analyzer from cached walk-forward runs.

Usage: uv run python scripts/residual_edge_inputs.py --key <run key> [--key ...] --out-dir reports/<dir>

For each run: daily returns of the stitched out-of-sample equity, regressed (by the external analyzer) on
baselines that were declared before looking at the result:
  - buy_hold:  holding the same coin (primary model)
  - sma200:    the same coin, long when the previous daily close was above its 200-day SMA, else flat,
               0.1% fee per switch (a naive trend copy)
  - regime:    "bull"/"bear" = previous daily close above/below the 200-day SMA
Writes <symbol>_<variant>.csv plus a matching .json config for analyze_residual_edge.py.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd  # noqa: E402

import research_cache  # noqa: E402
from data import load_klines  # noqa: E402

SMA_DAYS = 200
SWITCH_FEE = 0.001


def build(key: str, out_dir: Path) -> Path:
    spec = json.loads((research_cache.ROOT / key / "spec.json").read_text())
    eq = research_cache.load(key)["equity"]
    strat = eq.resample("1D").last().ffill().pct_change().dropna()

    # Daily closes with enough history before the OOS start for the 200-day SMA
    start = (strat.index[0] - pd.Timedelta(days=SMA_DAYS + 10)).date()
    close = load_klines(spec["symbol"], "1d", start, strat.index[-1].date())["Close"]
    close.index = close.index.normalize()
    bh = close.pct_change()
    above = (close > close.rolling(SMA_DAYS).mean()).shift(1)  # decided on yesterday's close
    pos = above.astype(float)
    sma = pos * bh - pos.diff().abs().fillna(0) * SWITCH_FEE

    df = (strat.rename("strategy_return").to_frame()
          .join(bh.rename("buy_hold_return"), how="inner")
          .join(sma.rename("sma200_return"), how="inner")
          .join(above.map({True: "bull", False: "bear"}).rename("trend_regime"), how="inner")
          .dropna())
    df.index = df.index.strftime("%Y-%m-%d")
    variant = "vt" if spec["params"].get("vol_target") else "stop"
    name = f"{spec['symbol']}_{spec['params'].get('signal_tf', 'base')}_{variant}"
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / f"{name}.csv", index_label="date")
    config = {
        "schema_version": "1.0",
        "date_column": "date",
        "strategy_column": "strategy_return",
        "return_unit": "decimal",
        "frequency": "daily",
        "annualization_factor": 365,  # crypto trades every calendar day
        "primary_model": {"name": "buy_hold", "baseline_columns": ["buy_hold_return"]},
        "sensitivity_models": [
            {"name": "sma200_trend", "baseline_columns": ["sma200_return"]},
            {"name": "buy_hold_plus_sma200", "baseline_columns": ["buy_hold_return", "sma200_return"]},
        ],
        "regime_columns": ["trend_regime"],
        "rolling_window": 90,
        "minimum_observations": 60,
        "minimum_regime_observations": 20,
        "minimum_rolling_windows": 12,
        "hac_lags": "auto",
        "include_series": False,
        "data_declarations": {
            "baseline_selection": "predeclared",
            "strategy_return_basis": "net",
            "baseline_return_basis": "net",
            "analysis_scope": "out_of_sample",
            "universe_data": "not_applicable",
        },
    }
    (out_dir / f"{name}.json").write_text(json.dumps(config, indent=2))
    print(f"{name}: {len(df)} days {df.index[0]} -> {df.index[-1]} (run {key})")
    return out_dir / f"{name}.csv"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", action="append", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args()
    for k in a.key:
        build(k, a.out_dir)
