# Cursor plan — review WS-age fix, merge if good

Date: 2026-08-24
Agent: `bc-c4d67d3d-365b-4eab-99d0-1b4db16f4f4a`
Repo: Cryptokid92/polymarket-arb-team
Starting ref: `fix/ws-age-not-book-age` (`5010bbf`)

Paper only. Never create `ALLOW_LIVE`. Never place live orders. Do not loosen `stale_ms`, `min_edge`, `max_gap`, universe filters, or risk.

## Expected change
`ws_age_ms` is last stream/poll receive time, not `Book.ts_ms`. First REST snapshot counts as a receive. `trip(reason)` persists `halt_reason`. No auto-resume.

## Review
1. Diff vs main. `evaluate()` uses heartbeat age, not book `ts`.
2. First trip reason is kept.
3. Tests: old book `ts` after a fresh receive does not halt; silence > `ws_stale_ms` still trips.
4. `uv run pytest` green.
5. No live-gate regressions, no secrets.

## If pass
User asked: squash-merge to main. No force-push.

## If fail
Do not merge. List blockers.
