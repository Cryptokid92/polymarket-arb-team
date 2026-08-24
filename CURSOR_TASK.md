# Cursor review — Task 5 only

Review the Task 5 risk-agent commit. Do not implement Tasks 6–12.

## Run

```bash
uv run pytest tests/test_risk.py tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, or state databases.

## Check

- One pass: `gap_3c` + healthy flags + empty portfolio + default settings (may clip notional).
- Hard rejects: halted, not binary, not accepting orders, `seconds_delay > 0`, `neg_risk`, stale book (`stale_one_side.json`), `raw_edge > max_gap`, `open_pairs` cap, daily loss, uncompletable walk, notional that cannot clip.
- `delayed_market.json` is used for the delay reject.
- After a clip, both sides are re-walked at the same size.
- Decimal only.
