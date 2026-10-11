import numpy as np
import pandas as pd
import pytest

import research_cache


@pytest.fixture(autouse=True)
def _no_research_db(monkeypatch):
    """Tests never write research runs to the real database."""
    monkeypatch.setattr(research_cache, "DB_ENABLED", False)


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    """Deterministic synthetic 5m OHLCV: random walk with trending and ranging regimes."""
    rng = np.random.default_rng(42)
    n = 4000
    drift = np.where((np.arange(n) // 500) % 2 == 0, 0.0004, -0.0002)
    close = 30_000 * np.exp(np.cumsum(drift + rng.normal(0, 0.003, n)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.002, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    vol = rng.lognormal(3, 0.6, n)
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)
