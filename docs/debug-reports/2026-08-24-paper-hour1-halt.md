# Hour-1 halt — book age used as WS age

Date: 2026-08-24
Data: `data/paper-hour1/state.sqlite` (gitignored)

## State
- `meta.halted=1`
- No `HALT` file
- fills, open_orders, hedge_incidents empty
- `daily_pnl` unset (0)
- rejects: all `neg_risk` (156 after two scans)
- Runner process gone. UI still up.

## Cause
`KillSwitch.evaluate` trips `ws_stale` when `ws_age_ms > ws_stale_ms` (3000). That means stream silence.

`consider()` passed book quote age:

```
ws_age_ms=max(0, now_ms - min(yes.ts_ms, no.ts_ms))
```

CLOB REST book timestamps are often older than 3s. First consider on the 2 universe markets tripped halt. No auto-resume. Book staleness already has `stale_ms=400`. Risk was not loosened.

`trip()` did not store a reason (added later).

## Fix
Grok Build commit `5010bbf` on `fix/ws-age-not-book-age`. Cursor review passed. Merged to main as `42e4384`. See plans and the review report.
