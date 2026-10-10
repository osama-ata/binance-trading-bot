"""Backtest-validity checks (TODO §4.1), modelled on Freqtrade's lookahead- and recursive-analysis.

- `lookahead_check`: indicators and signals computed on history truncated at bar t must equal the same row
  computed on the full history. Any difference means the strategy peeks at the future.
- `recursive_check`: indicators computed with only N bars of history (what the live engine keeps) must match
  the full-history values. Large differences mean the warm-up is too short (EMAs not converged).

Run on real data: uv run python src/validation.py BTCUSDT 5m 2026-07-01
"""
import numpy as np
import pandas as pd

from strategies import BaseStrategy

OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _rel_diff(a: pd.Series, b: pd.Series, scale: pd.Series) -> pd.Series:
    """|a-b| relative to max(|b|, typical column magnitude); NaN-vs-value counts as 1.0, NaN-vs-NaN as 0."""
    both_nan = a.isna() & b.isna()
    one_nan = a.isna() ^ b.isna()
    denom = np.maximum(b.abs().fillna(0), scale.reindex(b.index).fillna(1e-12)).replace(0, 1e-12)
    d = ((a - b).abs() / denom).fillna(0.0)
    d[one_nan] = 1.0
    d[both_nan] = 0.0
    return d


def _numeric(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.astype(float)


def lookahead_check(strategy: BaseStrategy, df: pd.DataFrame, cuts: list[int], rtol: float = 1e-9) -> list[dict]:
    """Return a list of mismatches (empty = no look-ahead). `cuts` are positional indices into df."""
    full = strategy.prepare(df)
    scale = _numeric(full).abs().median()
    problems = []
    for t in cuts:
        part = strategy.prepare(df.iloc[: t + 1])
        a, b = _numeric(part.iloc[[-1]]).iloc[0], _numeric(full.iloc[[t]]).iloc[0]
        d = _rel_diff(a, b, scale)
        bad = d[d > rtol]
        if len(bad):
            problems.append({"bar": df.index[t], "columns": bad.to_dict()})
        sig_part = strategy.entry_signal(part, len(part) - 1)
        sig_full = strategy.entry_signal(full, t)
        if (sig_part is None) != (sig_full is None) or (
            sig_part and sig_full and not np.allclose([sig_part.stop, sig_part.target], [sig_full.stop, sig_full.target])
        ):
            problems.append({"bar": df.index[t], "signal": (sig_part, sig_full)})
    return problems


def default_cuts(strategy: BaseStrategy, df: pd.DataFrame, n: int = 200, seed: int = 0) -> list[int]:
    """Every signal bar (up to n/2), bars inside forming higher-timeframe candles, and random bars."""
    full = strategy.prepare(df)
    start = min(strategy.warmup_bars(df.index[1] - df.index[0]), len(df) // 2)
    signals = [i for i in range(start, len(df)) if strategy.entry_signal(full, i)]
    rng = np.random.default_rng(seed)
    signals = list(rng.choice(signals, size=min(len(signals), n // 2), replace=False)) if signals else []
    mid_hour = [i for i in range(start, len(df)) if df.index[i].minute in (20, 25, 35)]
    mid_hour = list(rng.choice(mid_hour, size=min(len(mid_hour), n // 4), replace=False)) if mid_hour else []
    rest = list(rng.integers(start, len(df), size=max(n - len(signals) - len(mid_hour), 0)))
    return sorted({int(i) for i in signals + mid_hour + rest})


def recursive_check(strategy: BaseStrategy, df: pd.DataFrame, history_bars: list[int],
                    eval_points: int = 20) -> pd.DataFrame:
    """Max relative difference per indicator column when only N bars of history precede each evaluation point.

    Returns a frame indexed by N with one column per indicator (OHLCV excluded) plus `max`.
    """
    full = strategy.prepare(df)
    cols = [c for c in full.columns if c not in OHLCV and not c.startswith("prev:") and c != "signal_bar"]
    scale = _numeric(full[cols]).abs().median()
    longest = max(history_bars)
    points = np.linspace(longest, len(df) - 1, eval_points).astype(int)
    rows = {}
    for n in history_bars:
        worst = pd.Series(0.0, index=cols)
        for t in points:
            part = strategy.prepare(df.iloc[t - n + 1: t + 1])
            d = _rel_diff(_numeric(part[cols].iloc[[-1]]).iloc[0], _numeric(full[cols].iloc[[t]]).iloc[0], scale)
            worst = np.maximum(worst, d)
        rows[n] = worst
    out = pd.DataFrame(rows).T
    out["max"] = out.max(axis=1)
    out.index.name = "history_bars"
    return out


if __name__ == "__main__":
    import sys

    from data import load_klines
    from strategies import STRATEGIES

    symbol, interval, start = (sys.argv[1:4] + ["BTCUSDT", "5m", "2026-07-01"][len(sys.argv[1:4]):])
    data = load_klines(symbol, interval, start)
    bar = data.index[1] - data.index[0]
    pd.set_option("display.width", 200)
    for name, cls in STRATEGIES.items():
        s = cls()
        warm = s.warmup_bars(bar)
        sizes = sorted({20, 40, 80, 150, 300, 999, warm, warm + 50})
        sizes = [n for n in sizes if n < len(data) // 2]
        rec = recursive_check(s, data, sizes, eval_points=10)
        cuts = default_cuts(s, data, n=60)
        la = lookahead_check(s, data, cuts)
        print(f"\n## {name} (warmup {warm} bars) — look-ahead mismatches: {len(la)} / {len(cuts)} cuts")
        print((rec[["max"]] * 100).round(4).rename(columns={"max": "max diff %"}).T.to_string())
