# Progress

Task 1 is done (merged `15db598`). Cursor: OK.

Task 2 is done: protocol taker fee math, rebates excluded from EV.

- `uv run pytest tests/test_fees.py tests/test_money.py -q` — 18 passed
- Official table: 100 crypto @ $0.50 → $1.75; @ $0.01 → $0.07
- 3¢ raw edge on 100 shares minus two crypto peak fees is negative
- Geopolitics `fee_rate=0` → taker fees 0
- Maker path fee is 0; `net_edge_maker` does not add a rebate
- `ALLOW_LIVE` was not created. Live trading is not enabled.
- Remaining: paper-only Tasks 3–11. Task 12 stays dark.
