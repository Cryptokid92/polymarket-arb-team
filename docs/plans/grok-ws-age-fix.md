# Task: fix paper kill-switch WS-age wiring

Repo: /workspace/polymarket-arb-team
Public origin: https://github.com/Cryptokid92/polymarket-arb-team
Paper only. Never create ALLOW_LIVE. Never place live orders. Never commit .env, secrets, data/, sqlite, JSONL.

## Bug
The hour paper run halted with meta.halted=1, no HALT file, empty fills/hedge_incidents, daily_pnl=0. All rejects were neg_risk.

Root cause: `KillSwitch.evaluate` trips `ws_stale` when `ws_age_ms > settings.ws_stale_ms` (default 3000). That means websocket/stream silence age.

`run_paper` / `consider()` in `src/arb/app.py` incorrectly passes book quote age:

    ws_age_ms=max(0, now_ms - min(yes.ts_ms, no.ts_ms))

CLOB REST book timestamps are often older than 3s, so the first consider() trips halt permanently (no auto-resume). Book staleness is already rejected separately via `stale_ms=400`. Do not loosen stale_ms, min_edge, max_gap, universe filters, or risk.

## Required fix
1. Track last stream/poll *receive* time (when `_apply_update` / `_updates` delivers an event or a poll snapshot arrives). Pass that age as `ws_age_ms` to `evaluate`.
2. First snapshot apply after fetch counts as a receive (age ~0). Do not use `Book.ts_ms` as WS age.
3. Persist the trip reason (e.g. meta `halt_reason`) when `trip(reason)` is called. Dashboard/report can read it later. Do not auto-resume.
4. Tests: book ts older than 3000ms must NOT trip halt if a stream/poll just arrived. Real WS silence > ws_stale_ms MUST still trip. Existing killswitch tests stay valid. Add paper-loop coverage if needed.
5. TDD. Run `uv run pytest` and leave it green.
6. Implement in this clone. Commit on a branch `fix/ws-age-not-book-age` (not main). Do not push unless git remote works and you can open a PR. Do not force-push. Do not merge.

Read AGENTS.md. One writer. Decimal money stays. Official SDK only.

Report: files changed, tests run, commit hash, whether you opened a PR.
