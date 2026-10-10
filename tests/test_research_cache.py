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
