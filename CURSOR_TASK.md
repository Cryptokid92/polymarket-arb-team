# Cursor review — Task 4 only

Review the Task 4 hunter commit. Do not implement Tasks 5–12.

## Run

```bash
uv run pytest tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, or state databases.

## Check

- `gap_3c.json` emits `GapFound` with fillable 80 and `raw_edge == 0.03`.
- `no_gap.json` returns None.
- Bid-only completeness (asks still sum >= `1 - min_edge`) returns None.
- `book_age_ms` on `stale_one_side.json` uses the older book `ts_ms`.
- Hunt sizes with `fillable_pair_size` + `walk_asks` on asks only — not bids or mids.
- `raw_edge = 1 - yes_vwap - no_vwap` and is never rounded up.
- Decimal only.
