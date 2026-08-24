# Progress

Task 1 is done (merged `15db598`). Cursor: OK.

Task 2 is done (merged `0c890a1`). Cursor: OK.

Task 3 is done (merged `2eaac20`). Cursor: OK.

Task 4 is done (merged `b57f722`). Cursor: OK.

Task 5 is done: risk agent refuses uncompletable and delayed markets.

- `uv run pytest tests/test_risk.py tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q` — 45 passed
- Pass: `gap_3c` + healthy flags + empty portfolio + default settings (notional clipped)
- Rejects: halted, not binary, not accepting, delay, neg-risk, stale, max_gap, open pairs, daily loss, uncompletable walk, unclippable notional
- `ALLOW_LIVE` was not created. Live trading is not enabled.
- Remaining: paper-only Tasks 6–11. Task 12 stays dark.
