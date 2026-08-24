# Hour-6 — fat `get_order_books` payload

Date: 2026-08-24
Paper only. No `ALLOW_LIVE`. No orders.

Hour-6 paper run on main `a4b8fe0` (`--all-markets`):

- listed 5000 (safety cap)
- universe 1540
- rejects 3460 (3352 `neg_risk`)
- then `get_order_books` for all universe token ids failed: `paper_run: public API is unreachable: Payload exceeds the limit`
- process exited
- no hour watch

`--all-markets` listing was already paginated (`LIST_PAGE_SIZE=100`, ceiling 5000). Raising `LIST_SAFETY_CAP` is not the fix. The crash was one REST books call with ~3080 token ids after the v1 filter.

Fix: batch `get_order_books` (default 50 token ids), apply each batch, log/continue a failed batch. Watch 40 pairs (80 tokens), rotate the rest every 90s. Caps and universe rules stay tight.

See [cursor-batch-books-rotate.md](../plans/cursor-batch-books-rotate.md).
