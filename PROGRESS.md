# Progress

Task 1 is done (merged `15db598`). Cursor: OK.

Task 2 is done (merged `0c890a1`). Cursor: OK.

Task 3 is done (merged `2eaac20`). Cursor: OK.

Task 4 is done (merged `b57f722`). Cursor: OK.

Task 5 is done (merged `c3fc647`). Cursor: OK.

Task 6 is done (merged `d2d2acc`). Cursor: OK.

Task 7 is done (merged `0f46af0`). Cursor: OK.

Task 8 is done (merged `13c0fa0`). Cursor: OK.

Task 9 is done (merged `b67c958`). Cursor: OK.

Task 10 is done: recorded-book backtest with adversarial lie detectors.

- `uv run pytest tests/test_backtest.py tests/test_adversary.py …` — 92 passed
- Honest replay fills at ask VWAP, not mid; hedges sell into bids
- `p_miss=1` fails the second FAK (naked incident, not a completed pair)
- Vanished second ask before `t+latency` is not a completed pair
- Crypto 50¢ books with a 2¢ gap are not profitable as taker after protocol fees
- `detect_mid_fill` / `detect_lookahead` catch lying engines
- `scripts/record_books.py` refuses `--place-orders` and does not call the network
- `ALLOW_LIVE` was not created. Live trading is not enabled. No secrets committed.
- Remaining: paper-only Task 11. Task 12 stays dark.
