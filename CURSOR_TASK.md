# Cursor review — batch books + rotate watch slice (not Task 12)

Review the paper book-batch and watch-slice work. Do **not** implement Task 12. Do **not** create `ALLOW_LIVE`.

## Run

```bash
uv run pytest -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not construct `AsyncSecureClient`.
- Do not call the live network in default tests.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, `data/`, sqlite, or paper JSONL with account data.
- Do not loosen universe or risk: still refuse neg-risk, delay, non-binary, short crypto windows, `stale_ms`, `min_edge`, `max_gap`.
- Do not raise `LIST_SAFETY_CAP` as the payload-limit “fix”.

## Check — batched books

- REST `get_order_books` is called in batches (`BOOK_BATCH_SIZE = 50` token ids). Not one call of all universe ids.
- Each successful batch is applied. Heartbeat / `stats.json` rewrite so the UI can show running.
- Failed batch: log `book_batch_failed`, continue. `PublicApiError` only if listing is dead or **every** book batch fails.
- Kill-switch quiet-WS REST probe is batched too.

## Check — watch slice + rotate

- Do not subscribe/poll all ~1540 pairs at once.
- Default watch: `WATCH_PAIRS = 40` (80 tokens). Documented as fitting official payload limits.
- Remaining pairs rotate on `WATCH_ROTATE_S = 90`.
- Flags: `--book-batch-size`, `--watch-pairs`, `--watch-rotate-s`.
- Listing stays paginated / `--all-markets`. Safety cap stays 5000.

## Check — live gate

- `live_allowed()` is still false without a human `ALLOW_LIVE` dated today, and false when `ARB_MODE=paper`.
- Paper runner cannot place live orders.
- No `ALLOW_LIVE` file in the repo.

## Check — docs

- `docs/plans/cursor-batch-books-rotate.md`
- `docs/debug-reports/2026-08-24-hour6-payload-limit.md`
- README indexes + flags in README / `docs/guide/how-this-bot-works.md`
