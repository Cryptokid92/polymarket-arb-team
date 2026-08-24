# Plan (paper-only)

Not financial advice. No guaranteed PnL. Do not enable live trading. Do not create `ALLOW_LIVE`.

## Task 1 — Scaffold — done

Repo layout, MIT license, paper-default `Settings`, Decimal money helpers, dual live gate. Cursor: OK `15db598`.

## Task 2 — Fees (pure function) — done

Protocol taker fee `C * feeRate * p * (1-p)`. Makers pay 0. Never include maker rebates in EV. Cursor: OK `0c890a1`.

## Task 3 — Book store + ask walk — done

Reconstruct YES/NO books from snapshots + `price_change` deltas. Walk ask depth (VWAP); do not size by mid or top-of-book only. Cursor: OK `2eaac20`.

## Task 4 — Hunter — done

Emit `GapFound` only for depth-sized ask gaps (`yes_vwap + no_vwap <= 1 - min_edge` and fillable >= min_size). Uses asks, never mids. Cursor: OK `b57f722`.

## Task 5 — Risk agent — done

Refuse halted, non-binary, delayed, neg-risk, stale, too-good, over-pair, daily-loss, uncompletable, and over-notional gaps. May clip size to `max_notional_per_trade` and re-walk both sides. Cursor: OK `c3fc647`.

## Task 6 — Fee agent — done

Prefer `maker_gtc` when maker EV > 0. Allow `taker_fak` only if taker EV > 0 after protocol fees + `0.005`/share buffer. Rebates never in EV. Cursor: OK `d2d2acc`.

## Task 7 — Paper executor + bus wiring — done

In-process bus. `run_pipeline` (hunt → risk → intent). `PaperBroker` writes JSONL under gitignored `data/`. `LiveBroker` raises unless `live_allowed()`. Tests: `uv run pytest tests/test_executor_paper.py tests/test_fee_agent.py tests/test_risk.py tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q`.

## Remaining (paper only)

8. Merge + naked-leg hedge (simulated)
9. Kill switch, state dump, preflight
10. Recorder + backtest + adversary
11. Paper runner (networked, no orders)
12. Live path (build dark, do not run) — not now
