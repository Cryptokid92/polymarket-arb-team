# Progress

Task 1 is done (merged `15db598`). Cursor: OK.

Task 2 is done (merged `0c890a1`). Cursor: OK.

Task 3 is done (merged `2eaac20`). Cursor: OK.

Task 4 is done: hunter flags depth-sized ask gaps.

- `uv run pytest tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q` — 32 passed
- `gap_3c` emits `GapFound` (fillable 80, raw_edge 0.03)
- `no_gap` and bid-only completeness are silent
- `book_age_ms` uses the older book ts
- Hunt sizes from asks only
- `ALLOW_LIVE` was not created. Live trading is not enabled.
- Remaining: paper-only Tasks 5–11. Task 12 stays dark.
