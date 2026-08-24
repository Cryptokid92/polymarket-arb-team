# Cursor plan — quiet live WS must not trip `ws_stale`

Date: 2026-08-24
Agent: Cursor implementer
Starting ref: `main` (`511426c`) after PR #15

Paper only. Never create `ALLOW_LIVE`. Never place orders. Do not loosen hunter `stale_ms` (400), `min_edge`, `max_gap`, universe filters, or daily-loss/hedge kill rules. Do not auto-resume after a real halt. Do not raise `ws_stale_ms` to minutes. Do not delete `watch_silence`.

## Bug
Hour-4 paper run on `511426c` stayed alive but KillSwitch tripped:

- `data/paper-hour4/state.sqlite` meta: `halted=1`, `halt_reason=ws_stale`
- No `HALT` file
- Process still running
- 80 listed, 2 universe, 0 gaps, 78 `neg_risk`

`StreamHeartbeat` was marked only on subscribe/poll *book updates*. `watch_silence()` called `evaluate(ws_age_ms=heartbeat.age_ms)` on a timer. Default `ws_stale_ms=3000`. Polymarket WS can send nothing while prices do not change. Quiet book ≠ dead socket. Book quote age stays a separate `stale_ms=400` reject.

## Required behavior
- Dead stream (subscribe iterator ends/errors, or poll fetch fails) still trips `ws_stale`. Persist `halt_reason`. No auto-resume.
- A live subscribe that is simply quiet must not halt.
- Fail-closed liveness: if no WS event for approaching `ws_stale_ms`, REST `get_order_books`, mark heartbeat on successful receive, apply books. If that poll fails, then trip `ws_stale`.

## Tests
TDD in `tests/test_paper_run.py`. `uv run pytest` green.

## Git
Branch + PR. Do not merge to main.
