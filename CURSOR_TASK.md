# Cursor review — paper bankroll, PnL, local controls (not Task 12)

Review the paper $500 bankroll + dashboard control work. Do **not** implement Task 12. Do **not** create `ALLOW_LIVE`.

Paper only. Never place live orders. Never construct a trading client in the UI. Do not loosen universe/risk.

## Check — bankroll and settlement

- Default paper bankroll is `Decimal("500")` (`PAPER_BANKROLL` / `--paper-bankroll`).
- `max_notional_per_trade` still clips size. Caps unchanged.
- Successful intents paper-fill both legs at VWAPs. Taker fees via existing helpers. Makers 0. No rebate.
- Completeness: $1/share. PnL = size * (1 - yes_vwap - no_vwap) - pair_fees.
- Refuse `insufficient_bankroll` when cost > remaining bankroll. Do not go negative silently.
- sqlite under the data dir holds fills / `daily_pnl` / bankroll. No secrets.

## Check — stats + UI

- `write_paper_stats` includes `bankroll` and `daily_pnl` (heartbeat still works).
- Dashboard shows bankroll, earned/lost, intents, fills. Banner PAPER MODE.
- Start/Stop: pause/resume control file; Start execs `paper_run` if no pid. Stop does not cancel live orders.
- Slider writes watch-rotate 10–120s. Does not change `stale_ms`, `min_edge`, `max_gap`, universe filters, or bankroll rules.
- GET for data. Control POST local-only. No new web deps.

## Check — tests and hygiene

- `uv run pytest` green.
- Official SDK types only on the public runner path.
- No `.env`, `ALLOW_LIVE`, or `data/` sqlite in the PR.
