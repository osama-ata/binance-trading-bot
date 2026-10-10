"""Persistent cache for research runs (walk-forward, overfitting stats), so identical runs are never repeated.

A run is keyed by its full specification (strategy, symbol, interval, dates, costs, fixed params, grid, ...)
plus a fingerprint of the code that determines results (strategies, indicators, risk, backtester, data
loading) and the backtesting/pandas versions. Change any of those and the key changes, so stale results are
never reused. Results live in data/research/<key>/ (gitignored, like the kline cache):

    spec.json      the inputs
    summary.json   headline numbers (OOS return, drawdown, trades, DSR, PBO, ...)
    folds.csv      per-fold chosen params and test results
    equity.parquet stitched out-of-sample equity curve

data/research/index.csv gets one line per computed run, for browsing.
"""
import fcntl
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent / "data" / "research"
# Files whose contents change backtest results. Engine/broker/dashboard code does not.
RESULT_CODE = ["backtester.py", "risk.py", "indicators.py", "overfitting.py", "data.py", "binance_client.py",
               "strategies/*.py"]


@lru_cache(maxsize=1)
def code_fingerprint() -> str:
    import backtesting

    h = hashlib.sha256()
    for pattern in RESULT_CODE:
        for path in sorted(SRC.glob(pattern)):
            h.update(path.relative_to(SRC).as_posix().encode())
            h.update(path.read_bytes())
    h.update(f"backtesting={backtesting.__version__};pandas={pd.__version__}".encode())
    return h.hexdigest()[:16]


def run_key(spec: dict[str, Any]) -> str:
    payload = json.dumps({**spec, "_code": code_fingerprint()}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def load(key: str) -> dict | None:
    d = ROOT / key
    if not (d / "summary.json").exists():
        return None
    out = {"summary": json.loads((d / "summary.json").read_text())}
    if (d / "folds.csv").exists():
        out["folds"] = pd.read_csv(d / "folds.csv")
    if (d / "equity.parquet").exists():
        out["equity"] = pd.read_parquet(d / "equity.parquet")["equity"]
    return out


def save(key: str, spec: dict, summary: dict, folds: pd.DataFrame | None = None,
         equity: pd.Series | None = None) -> Path:
    d = ROOT / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps({**spec, "_code": code_fingerprint()}, indent=2, default=str))
    (d / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    if folds is not None:
        folds.to_csv(d / "folds.csv", index=False)
    if equity is not None and len(equity):
        equity.rename("equity").to_frame().to_parquet(d / "equity.parquet")
    index = ROOT / "index.csv"
    row = pd.DataFrame([{"key": key, "code": code_fingerprint(), **{f"spec.{k}": v for k, v in spec.items()},
                         **summary}])
    with open(ROOT / ".index.lock", "w") as lock:  # parallel report workers append concurrently
        fcntl.flock(lock, fcntl.LOCK_EX)
        row.to_csv(index, mode="a", header=not index.exists(), index=False)
    return d
