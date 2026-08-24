# Cursor plan — batch REST books and rotate the watch slice

Date: 2026-08-24
Agent: Grok implementer
Starting ref: `main` (`a4b8fe0`) after PR #20

Paper only. Never create `ALLOW_LIVE`. Never place orders. Do not loosen hunter `stale_ms`, `min_edge`, `max_gap`, universe filters (neg-risk, delay, non-binary, short crypto windows), or kill rules. Do not raise `LIST_SAFETY_CAP` as the fix.

## Bug

Hour-6 `--all-markets` on `a4b8fe0` listed 5000 (safety cap): universe 1540, rejects 3460 (3352 `neg_risk`). Then one `get_order_books` for all universe token ids (~3080) failed: `paper_run: public API is unreachable: Payload exceeds the limit`. Process exited. No hour watch.

Listing pagination was correct. The fat book payload was not.

## Design (Nikolai approved)

1. REST `get_order_books` in small batches. Default `BOOK_BATCH_SIZE = 50` token ids (not 3080). Apply each batch. One fat payload must not kill the run.
2. Do **not** subscribe/poll all 1540 pairs at once. Watch a first slice: default `WATCH_PAIRS = 40` (80 tokens). That fits official CLOB / `MarketSpec` payload limits. Rotate remaining universe pairs every `WATCH_ROTATE_S = 90` seconds so more of the 1540 are looked at during the hour (~1600 pair-looks).
3. Listing stays paginated / `--all-markets`. `LIST_SAFETY_CAP` stays 5000.
4. Failed batch: log `book_batch_failed`, continue other batches. `PublicApiError` only if the listing itself is dead or **every** book batch fails.
5. Heartbeat / `stats.json` rewrite after each batch so the UI can show running. Kill-switch quiet-WS REST probe is batched too.
6. Official SDK only. TDD. Paper only.

Flags: `--book-batch-size`, `--watch-pairs`, `--watch-rotate-s`.

## Tests

TDD in `tests/test_paper_run.py`. `uv run pytest -q` green. Offline mocks.

## Git

Branch + PR. Do not merge to main.
