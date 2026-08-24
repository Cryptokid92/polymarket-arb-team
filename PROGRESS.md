# Progress

Task 1 is done (merged `15db598`). Cursor: OK.

Task 2 is done (merged `0c890a1`). Cursor: OK.

Task 3 is done (merged `2eaac20`). Cursor: OK.

Task 4 is done (merged `b57f722`). Cursor: OK.

Task 5 is done (merged `c3fc647`). Cursor: OK.

Task 6 is done: fee agent prefers maker and refuses negative-EV taker.

- `uv run pytest tests/test_fee_agent.py tests/test_risk.py tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q` — 49 passed
- Crypto 3¢ @ 0.55/0.42 fee 0.07: `maker_gtc`; taker EV <= 0
- Fee-free 3¢: both EV positive; still maker
- Both EV <= 0 → None
- `ALLOW_LIVE` was not created. Live trading is not enabled.
- Remaining: paper-only Tasks 7–11. Task 12 stays dark.
