# Cursor review — Task 2 only

Review the Task 2 fees commit. Do not implement Tasks 3–12.

## Run

```bash
uv run pytest tests/test_fees.py tests/test_money.py -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, or state databases.
- Do not add maker rebates to EV.

## Check

- `PLAN.md` lists the original product tasks (2 Fees, 3 Book store, … 12 live dark).
- `taker_fee(100, 0.50, 0.07) == 1.75` and `taker_fee(100, 0.01, 0.07) == 0.07`.
- Maker fee / `net_edge_maker` never add a rebate.
- 3¢ raw edge on 100 shares minus two crypto peak fees is negative (`net_edge_taker < 0`).
- Geopolitics `fee_rate=0` → taker fees 0.
- Public helpers are Decimal-only (no float).
