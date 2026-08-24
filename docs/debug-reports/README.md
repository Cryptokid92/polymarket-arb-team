# Debug reports

Write-ups after a halt, crash, review, or paper run. Plans live in `docs/plans/`.

Do not commit paper JSONL, sqlite, `.env`, or keys.

| File | When | What |
|---|---|---|
| [2026-08-24-paper-scans.md](2026-08-24-paper-scans.md) | Hour-1 and hour-2 paper scans | Public API counts. No gaps. |
| [2026-08-24-paper-hour1-halt.md](2026-08-24-paper-hour1-halt.md) | Hour-1 halt | Book age wired as WS age. |
| [2026-08-24-cursor-review-ws-age.md](2026-08-24-cursor-review-ws-age.md) | After Grok `5010bbf` | Cursor pass, merged `42e4384`. |
| [2026-08-24-paper-hour2-ws-decimal-crash.md](2026-08-24-paper-hour2-ws-decimal-crash.md) | Hour-2 runner death | Bad WS book field → ConversionSyntax. |
| [2026-08-24-cursor-6-agent-ws-decimal.md](2026-08-24-cursor-6-agent-ws-decimal.md) | After 6-lane debug | Exact field `min_order_size` → `"None"`. PR #15. |
| [2026-08-24-hour4-quiet-ws-stale.md](2026-08-24-hour4-quiet-ws-stale.md) | Hour-4 halt | Quiet live WS ≠ dead socket. |
| [2026-08-24-ui-stale-while-running.md](2026-08-24-ui-stale-while-running.md) | Hour-5 UI | Runner up, stats rewriting, UI said stale 11m. |
| [2026-08-24-hour6-payload-limit.md](2026-08-24-hour6-payload-limit.md) | Hour-6 crash | Fat `get_order_books` (~3080 ids) exceeded payload. |
