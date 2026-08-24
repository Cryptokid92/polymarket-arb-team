# Cursor review — Task 3 only

Review the Task 3 book-store commit. Do not implement Tasks 4–12.

## Run

```bash
uv run pytest tests/test_books.py tests/test_fees.py tests/test_money.py -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, or state databases.

## Check

- Fixtures exist under `tests/fixtures/books/`: `gap_3c.json`, `thin_depth.json`, `no_gap.json`, `stale_one_side.json`, `delayed_market.json`.
- `gap_3c`: fillable 80 and yes_vwap + no_vwap == 0.97.
- `thin_depth`: 5¢ gap but only 3 shares vs min_order 5 → fillable 0.
- `walk_asks` returns None when depth is insufficient.
- `BookStore` applies snapshots and `price_change` deltas; ts/hash update.
- Sizing walks the book (not mid / top-of-book only).
- Decimal only; no float money.
