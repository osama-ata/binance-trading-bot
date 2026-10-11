import pandas as pd

import research_cache as rc


def test_key_depends_on_spec_and_code(monkeypatch):
    spec = {"strategy": "x", "fee": 0.001}
    k1 = rc.run_key(spec)
    assert k1 == rc.run_key(dict(spec))
    assert k1 != rc.run_key({**spec, "fee": 0.00075})
    monkeypatch.setattr(rc, "code_fingerprint", lambda: "different-code")
    assert k1 != rc.run_key(spec)


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "ROOT", tmp_path)
    eq = pd.Series([100.0, 101.0], index=pd.date_range("2026-01-01", periods=2, freq="D", tz="UTC"))
    folds = pd.DataFrame({"rr": [2.0], "test_trades": [3]})
    rc.save("k1", {"strategy": "x"}, {"oos_return_pct": 1.0}, folds, eq)
    out = rc.load("k1")
    assert out["summary"]["oos_return_pct"] == 1.0
    assert out["folds"]["test_trades"].tolist() == [3]
    assert out["equity"].iloc[-1] == 101.0
    assert rc.load("missing") is None
    assert (tmp_path / "index.csv").read_text().count("\n") == 2


def test_record_db_upserts_research_runs(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from database import ResearchRun

    engine = create_engine(f"sqlite:///{tmp_path / 'r.db'}")
    ResearchRun.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(rc, "DB_ENABLED", True)
    monkeypatch.setattr(rc, "_db_sessions", lambda: factory)
    spec = {"kind": "walk_forward", "strategy": "opening_range", "symbol": "ETHUSDT", "interval": "5m",
            "params": {"signal_tf": "1h"}, "risk": {"max_position_pct": 1.0}, "_code": "abc"}
    summary = {"signal_tf": "1h", "oos_return_pct": 1.5, "dsr": float("nan"), "pbo": 0.25, "oos_trades": 7,
               "extra": [float("nan"), 1.0]}
    assert rc.record_db("k1", spec, summary)
    assert rc.record_db("k1", spec, {**summary, "oos_return_pct": 2.0})  # upsert, no duplicate
    with factory() as s:
        rows = s.execute(select(ResearchRun)).scalars().all()
    assert len(rows) == 1
    r = rows[0]
    assert (r.strategy, r.symbol, r.signal_tf, r.code, r.oos_return_pct, r.dsr, r.pbo, r.oos_trades) == (
        "opening_range", "ETHUSDT", "1h", "abc", 2.0, None, 0.25, 7)
    assert r.risk == {"max_position_pct": 1.0} and r.summary["extra"] == [None, 1.0]


def test_record_db_failure_does_not_raise(monkeypatch):
    def boom():
        raise RuntimeError("no db")

    monkeypatch.setattr(rc, "DB_ENABLED", True)
    monkeypatch.setattr(rc, "_db_failed", False)
    monkeypatch.setattr(rc, "_db_sessions", boom)
    assert rc.record_db("k", {}, {}) is False
    assert rc.record_db("k", {}, {}) is False  # gives up after the first failure
