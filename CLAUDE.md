# Working rules for this repo

- **Work directly on `main`.** Do not create feature branches.
- **Stage-by-stage delivery:** when executing a multi-stage plan (e.g. a phase in `TODO.md`), commit and push to `main` after **each** stage. In the same commit, update `TODO.md`: tick finished items, record results and measurements, and note deviations.
- **Start of a session:** read the handoff / progress log at the top of `TODO.md` first.

# Project notes

- Python 3.11, managed with `uv`. Fast tests: `uv run pytest -q -m "not slow"`; full validity checks: `uv run pytest -q`.
- Research: `uv run python scripts/wf_report.py --jobs 16 --out reports/<name>.md`. Runs are cached in `data/research/` (gitignored), keyed by the run spec plus a fingerprint of result-affecting code. Commit report tables under `reports/`.
- `.env` is not in git (see `.env.example`). Never commit secrets.
