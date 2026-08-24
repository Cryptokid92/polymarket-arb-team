# Cursor plan — paper $500 bankroll, PnL, and local dashboard controls

Date: 2026-08-24
Agent: Grok implementer
Starting ref: `main` (`fe91389`) after PR #21 (batch books + rotate watch)

Paper only. Never create `ALLOW_LIVE`. Never place live orders. Never construct a trading client in the UI. Do not loosen universe/risk (`stale_ms`, `min_edge`, `max_gap`, `max_notional_per_trade`, `WATCH_PAIRS`, `LIST_SAFETY_CAP`).

## Ask

Nikolai wants a **$500 paper bankroll** so the runner can “order” when hunt finds a completeness gap, and the dashboard shows earned/lost. Same PR: **Start / Stop** and a **watch-rotate slider** (10–120s) on the local paper UI.

Today `paper_run` logs intents and used to bump `open_pairs`. It did not simulate fills, merge, or PnL. Task 8 paper merge exists; this wires it into the paper hour loop.

## Design

1. `PAPER_BANKROLL` / `--paper-bankroll` default `Decimal("500")`. Notional still clipped by `max_notional_per_trade` (25).
2. When `choose_intent` succeeds, paper-fill both legs at intent/gap VWAPs. Taker FAK subtracts `pair_taker_fees`. Makers pay 0. Completeness settlement: pair is worth $1/share. Total PnL = `size * (1 - yes_vwap - no_vwap) - pair_fees`. No rebate.
3. Refuse if pair cost (`size * (yes_vwap + no_vwap) + pair_fees`) `>` remaining bankroll (`insufficient_bankroll`). Do not go negative silently.
4. Persist fills / `daily_pnl` / `bankroll` in the existing sqlite under the data dir. No account secrets.
5. `write_paper_stats` includes `bankroll` and `daily_pnl` (and `fills`) so the last-event heartbeat still works.
6. Dashboard: paper bankroll, realized PnL (earned/lost), intents, fills. Banner stays **PAPER MODE**.
7. Local control file `control.json`: Stop pauses the paper loop (no live cancel). Start resumes, or execs `scripts/paper_run.py` with `ARB_MODE=paper` if no pid is alive. Slider writes `rotate_s` (10–120); runner polls it for the existing watch-slice rotate. Does not change risk/universe caps.
8. GET remains the data path. `POST /api/control` is 127.0.0.1 only. No new web deps.

## Tests

TDD: `tests/test_paper_ledger.py`, `tests/test_paper_control.py`, plus updates to paper_run / paper_ui / state / money. `uv run pytest` green.

## Git

Branch + PR. Do not merge to main. No `.env`, no `ALLOW_LIVE`, no `data/` sqlite committed.
