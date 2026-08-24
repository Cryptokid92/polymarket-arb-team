# Hour-4 halt — quiet live WS treated as dead

Date: 2026-08-24
Code: main `511426c` (after PR #15)
Data: `data/paper-hour4` (gitignored)

## What happened
1. PR #15 stopped the WS `min_order_size=None` crash. `paper_run` stayed up.
2. KillSwitch still tripped: `meta.halted=1`, `halt_reason=ws_stale`.
3. No `HALT` file. Process still running.
4. Scan: 80 listed, 2 universe, 0 gaps, 78 `neg_risk`.

## Cause
`StreamHeartbeat` is last subscribe/poll *book update* receive time, not CLOB `Book.ts_ms`.

`watch_silence()` evaluates `ws_age_ms=heartbeat.age_ms` on a timer. `ws_stale_ms` default is 3000. If Polymarket WS sends nothing while prices do not change, age exceeds 3s and `evaluate` trips `ws_stale`.

Quiet book ≠ dead socket. Quote staleness is already a hunter/risk reject via `stale_ms=400`.

## Fix
Do not raise `ws_stale_ms`. Do not delete `watch_silence`.

When silence approaches `ws_stale_ms`, REST-poll `get_order_books`. Success marks the heartbeat and applies books. Failure (or subscribe iterator end/error, or poll-loop fetch fail) trips `ws_stale` and persists `halt_reason`. No auto-resume.

See [cursor-fix-quiet-ws-stale.md](../plans/cursor-fix-quiet-ws-stale.md).
