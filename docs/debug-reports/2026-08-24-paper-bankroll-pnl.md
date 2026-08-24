# Paper bankroll + dashboard controls (2026-08-24)

Paper only. Not real money.

## What was missing

Hour paper runs logged intents and incremented `open_pairs`. They did not paper-fill, merge, or update `daily_pnl`, so the dashboard could not show earned/lost. Task 8 `maybe_merge` existed and was unused in `run_paper`.

## What landed

- Default paper bankroll **$500** (`PAPER_BANKROLL` / `--paper-bankroll`). Decimal only.
- Successful intents paper-fill both legs at VWAPs, settle via paper merge ($1/share), update bankroll and `daily_pnl`.
- Taker fees from existing fee helpers. Makers 0. No rebate.
- `insufficient_bankroll` reject if cost exceeds remaining bankroll.
- sqlite + `fills.jsonl` + `stats.json` (`bankroll`, `daily_pnl`, `fills`, `heartbeat_ms`).
- Local UI Start/Stop (pause/resume; Start execs `paper_run` if none is up). Watch-rotate slider 10–120s writes `control.json`; does not change `stale_ms` / `min_edge` / `max_gap`.
- Banner still PAPER MODE. No live buttons. No `ALLOW_LIVE`.
