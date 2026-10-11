"""Backfill the Postgres `research_runs` table from the cached runs in data/research/.

Usage: uv run python scripts/research_db.py
Safe to rerun: rows are upserted by run key. New runs are written automatically by research_cache.save.
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import research_cache  # noqa: E402


def main() -> None:
    n = 0
    for d in sorted(research_cache.ROOT.glob("*/summary.json")):
        run = d.parent
        spec = json.loads((run / "spec.json").read_text())
        summary = json.loads(d.read_text())
        created = dt.datetime.fromtimestamp(d.stat().st_mtime, dt.timezone.utc)
        if not research_cache.record_db(run.name, spec, summary, created):
            sys.exit("database unavailable; is the compose db up and POSTGRES_PORT right?")
        n += 1
    print(f"upserted {n} runs into research_runs")


if __name__ == "__main__":
    main()
