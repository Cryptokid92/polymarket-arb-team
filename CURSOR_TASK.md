# Cursor review — Task 6 only

Review the Task 6 fee-agent commit. Do not implement Tasks 7–12.

## Run

```bash
uv run pytest tests/test_fee_agent.py tests/test_risk.py tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, or state databases.
- Do not add maker rebates to EV.

## Check

- Crypto 3¢ gap at 0.55/0.42 with `fee_rate` 0.07: `maker_gtc` approved, taker EV <= 0.
- Fee-free 3¢ gap: both EV positive; still prefer maker.
- Both EV <= 0 → `None`.
- `yes_limit` / `no_limit` are ask VWAPs.
- Only hardcoded extra is `Decimal("0.005")` per-share taker buffer.
- Decimal only.
