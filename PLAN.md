# Plan (paper-only)

Not financial advice. No guaranteed PnL. Do not enable live trading. Do not create `ALLOW_LIVE`.

## Task 1 — Scaffold — done

Repo layout, MIT license, paper-default `Settings`, Decimal money helpers, dual live gate. Cursor: OK `15db598`.

## Task 2 — Fees (pure function)

Protocol taker fee `C * feeRate * p * (1-p)`. Makers pay 0. Never include maker rebates in EV. Official table rounding (100 crypto @ $0.01 → $0.07). Tests: `uv run pytest tests/test_fees.py tests/test_money.py -q`.

## Remaining (paper only)

3. Book store + ask walk
4. Hunter
5. Risk agent
6. Fee agent
7. Paper executor + bus wiring
8. Merge + naked-leg hedge (simulated)
9. Kill switch, state dump, preflight
10. Recorder + backtest + adversary
11. Paper runner (networked, no orders)
12. Live path (build dark, do not run) — not now
