# Cursor plan — paper UI must follow the runner

Date: 2026-08-24
Agent: Grok implementer
Starting ref: `main` (`e761264`) after PR #17

Paper only. Never create `ALLOW_LIVE`. Never place orders. Do not loosen hunter `stale_ms`, `min_edge`, `max_gap`, universe filters, or kill rules. Do not invent a halt from a stale dashboard clock.

## Bug
Hour-5 on main: `paper_run` process up, not halted, `stats.json` still rewritten. UI showed **stale / last event 11m ago**.

`scripts/paper_ui.py` prefers the newest JSONL `ts_ms` (usually opening-universe `rejects.jsonl`). File mtime, including `stats.json`, is used only when no JSONL timestamp exists. A live runner that rewrites stats without new rejects looks dead.

## Required
- Last event / `run_status` must consider `stats.json` mtime and/or a `heartbeat_ms` field written by `write_paper_stats` / `run_paper`.
- Fresh rewrite or heartbeat inside a short window (a few seconds to ~15s) → **running**, not stale.
- Halt still comes only from `HALT` / sqlite `halt_reason`. Stale ≠ halt.
- Missing files still show zeros. Read-only. `127.0.0.1`. No new deps.

## Tests
TDD in `tests/test_paper_ui.py` (and heartbeat on `write_paper_stats` / `run_paper`). `uv run pytest` green.

## Git
Branch + PR. Do not merge to main.
