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
| [2026-08-24-paper-bankroll-pnl.md](2026-08-24-paper-bankroll-pnl.md) | Paper bankroll | $500 paper fills/PnL + local Start/Stop / rotate slider. |
| [2026-08-27-paper-evidence.md](2026-08-27-paper-evidence.md) | Paper evidence | `--all-markets` hour: near-miss histogram, tape backtest, Task 12 still dark. |
| [2026-08-28-honest-hour.md](2026-08-28-honest-hour.md) | Honest paper hour | PR 31 shown-take. Runner `fills=0` `daily_pnl=0`. Full tape: 0 completes, 1 naked, `net_pnl=-0.50`, `non_positive`. PR 30 still-at-bid on the same books was `+1442`. |
| [2026-08-28-honest-hour2.md](2026-08-28-honest-hour2.md) | Honest paper hour 2 | `gaps=0` `completed=0` one naked hedge `daily_pnl=-0.20`. Completeness frozen. |
| [2026-08-24-hour6-payload-limit.md](2026-08-24-hour6-payload-limit.md) | Hour-6 crash | Fat `get_order_books` (~3080 ids) exceeded payload. |
