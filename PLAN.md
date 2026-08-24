# Plan (paper-only)

Not financial advice. No guaranteed PnL. Do not enable live trading. Do not create `ALLOW_LIVE`.

## Task 1 — Scaffold — done

Repo layout, MIT license, paper-default `Settings`, Decimal money helpers, dual live gate. Cursor: OK `15db598`.

## Task 2 — Fees (pure function) — done

Protocol taker fee `C * feeRate * p * (1-p)`. Makers pay 0. Never include maker rebates in EV. Cursor: OK `0c890a1`.

## Task 3 — Book store + ask walk — done

Reconstruct YES/NO books from snapshots + `price_change` deltas. Walk ask depth (VWAP); do not size by mid or top-of-book only. Cursor: OK `2eaac20`.

## Task 4 — Hunter — done

Emit `GapFound` only for depth-sized ask gaps (`yes_vwap + no_vwap <= 1 - min_edge` and fillable >= min_size). Uses asks, never mids. Tests: `uv run pytest tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q`.

## Remaining (paper only)

5. Risk agent
6. Fee agent
7. Paper executor + bus wiring
8. Merge + naked-leg hedge (simulated)
9. Kill switch, state dump, preflight
10. Recorder + backtest + adversary
11. Paper runner (networked, no orders)
12. Live path (build dark, do not run) — not now
