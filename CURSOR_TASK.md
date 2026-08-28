# Cursor review — paper trading helper (not Task 12)

Review the paper trading-helper work. Do **not** implement Task 12. Do **not** create `ALLOW_LIVE`.

Paper only. Never place live orders. Do not loosen universe/risk.

## Check — near-miss

- `measure_pair` walks asks. Thin books have `raw_edge=None` (not top-of-book).
- Hunt still silent below `min_edge` 0.01.
- Dashboard / `report_paper` show closest pair and best edge this hour.
- Caps unchanged: `stale_ms` 400, `max_gap` 0.08, `LIST_SAFETY_CAP` 5000. Watch default is 100 pairs.

## Check — honest fills + recorder

- Networked `run_paper` uses `honest=True`. Instant both-leg fill is tests-only default.
- Taker miss hedges leftover and records a hedge incident. Maker rests then expires.
- `record_books.py` and `--record-books` use `AsyncPublicClient` only.
- `paper_run.py` source never contains `AsyncSecureClient`.

## Check — hot watch + alerts

- Pin ≤ 8 inside the 40-pair cap. Rotate the rest. Failed batches stay non-fatal.
- Alerts are local JSONL + dashboard only.

## Check — tests and hygiene

- `uv run pytest` green.
- No `.env`, `ALLOW_LIVE`, or `data/` sqlite in the PR.
- Task 12 stays dark.
