"""Overfitting statistics for parameter searches (TODO §4.2). Own implementation from the papers:

- Probabilistic / Deflated Sharpe Ratio: Bailey & López de Prado (2012, 2014), SSRN 1821643 / 2460551.
  DSR = PSR(SR*), where SR* is the Sharpe ratio the best of N *unskilled* trials would reach by luck.
- Probability of Backtest Overfitting via Combinatorially Symmetric Cross-Validation (CSCV):
  Bailey, Borwein, López de Prado & Zhu (2015), SSRN 2326253.

All Sharpe ratios here are per period (e.g. daily), not annualised.
"""
from itertools import combinations
from math import comb
from statistics import NormalDist

import numpy as np
import pandas as pd

N01 = NormalDist()
EULER_GAMMA = 0.5772156649015329


def sharpe(returns: np.ndarray | pd.Series) -> float:
    r = np.asarray(returns, dtype=float)
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return float(r.mean() / sd) if sd > 0 else 0.0


def probabilistic_sharpe(returns: np.ndarray | pd.Series, sr_benchmark: float = 0.0) -> float:
    """P(true SR > sr_benchmark) given the sample SR, its length, skewness and kurtosis."""
    r = pd.Series(np.asarray(returns, dtype=float)).dropna()
    t = len(r)
    if t < 3 or r.std(ddof=1) == 0:
        return float("nan")
    sr = sharpe(r)
    skew, kurt = float(r.skew()), float(r.kurt()) + 3.0  # pandas kurt() is excess kurtosis
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if denom <= 0:
        return float("nan")
    return float(N01.cdf((sr - sr_benchmark) * np.sqrt(t - 1) / np.sqrt(denom)))


def expected_max_sharpe(trial_sharpes: np.ndarray | list[float]) -> float:
    """SR* : expected maximum Sharpe of N trials with zero true skill, given the variance of their SRs."""
    srs = np.asarray(trial_sharpes, dtype=float)
    n = len(srs)
    if n < 2:
        return 0.0
    sd = srs.std(ddof=1)
    return float(sd * ((1 - EULER_GAMMA) * N01.inv_cdf(1 - 1 / n) + EULER_GAMMA * N01.inv_cdf(1 - 1 / (n * np.e))))


def deflated_sharpe(returns: np.ndarray | pd.Series, trial_sharpes: np.ndarray | list[float]) -> float:
    """Probability that the selected strategy's true SR is above what the best of N lucky trials would show.
    Values above ~0.95 are the usual bar for "not explained by the search"."""
    return probabilistic_sharpe(returns, expected_max_sharpe(trial_sharpes))


def pbo_cscv(returns: pd.DataFrame, n_blocks: int = 16, metric=sharpe, max_splits: int | None = None,
             seed: int = 0) -> dict:
    """Probability of Backtest Overfitting.

    `returns` is a T x N matrix: per-period returns of each of the N parameter combinations over the same
    periods. Rows are cut into `n_blocks` contiguous blocks; for every way of picking half the blocks as
    in-sample, the in-sample best combination's out-of-sample rank is recorded. PBO is the share of splits
    where that rank falls in the bottom half. ~0.5+ means the selection is no better than chance.
    """
    m = returns.to_numpy(dtype=float)
    t, n = m.shape
    if n < 2:
        raise ValueError("need at least 2 parameter combinations")
    n_blocks -= n_blocks % 2
    blocks = np.array_split(np.arange(t), n_blocks)
    splits = list(combinations(range(n_blocks), n_blocks // 2))
    if max_splits and len(splits) > max_splits:
        rng = np.random.default_rng(seed)
        splits = [splits[i] for i in rng.choice(len(splits), max_splits, replace=False)]
    logits, degradation = [], []
    for is_blocks in splits:
        is_idx = np.concatenate([blocks[b] for b in is_blocks])
        oos_idx = np.concatenate([blocks[b] for b in range(n_blocks) if b not in is_blocks])
        is_perf = np.array([metric(m[is_idx, j]) for j in range(n)])
        oos_perf = np.array([metric(m[oos_idx, j]) for j in range(n)])
        best = int(np.argmax(is_perf))
        rank = (oos_perf < oos_perf[best]).sum() + 0.5 * ((oos_perf == oos_perf[best]).sum() - 1) + 1  # 1..N
        omega = rank / (n + 1)
        logits.append(np.log(omega / (1 - omega)))
        degradation.append((is_perf[best], oos_perf[best]))
    logits = np.array(logits)
    deg = np.array(degradation)
    return {
        "pbo": float((logits < 0).mean()),
        "n_splits": len(splits),
        "n_splits_total": comb(n_blocks, n_blocks // 2),
        "median_logit": float(np.median(logits)),
        "is_sr_of_best": float(deg[:, 0].mean()),
        "oos_sr_of_best": float(deg[:, 1].mean()),
    }


def period_returns(equity: pd.Series, freq: str = "1D") -> pd.Series:
    """Per-period returns of an equity curve (default daily)."""
    return equity.resample(freq).last().ffill().pct_change().dropna()
