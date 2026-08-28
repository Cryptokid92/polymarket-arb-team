# Honest paper hour 2 — 28 Aug 2026

Paper only. No `ALLOW_LIVE`. No live orders. Not financial advice.

Stacked honesty head (`main` after PRs 31, 33-37). Shown-take maker rests. Hunt is `taker_fak` or skip. Still-at-bid does not fill.

Command:

```bash
ARB_MODE=paper uv run python scripts/paper_run.py --all-markets --seconds 3600 --record-books --data-dir data/paper-hour2
```

Data dir is gitignored. Do not commit JSONL, sqlite, or keys.

## Runner line

Runtime 3665 s. Exit 0.

```text
paper_run done: listed=5000 universe=77 gaps=0 maker_quotes=15384 intents=3320 completed=0 rejects={'neg_risk': 126195, 'not_accepting': 216, 'seconds_delay': 148175, 'short_crypto_window': 3120, 'max_open_pairs': 10998, 'book_batch_failed': 39} bankroll=499.80 daily_pnl=-0.20
```

`gt_0` / `gte_0.01` were 0. `best_edge=-0.001`. Hunt never fired.

## Fills

One `fills.jsonl` row. Maker GTC size 10, YES `0.85` + NO `0.14`. One side taken. Hedge flattened the leftover. `completed=false`, `naked=true`, `pnl=-0.20`. Completeness never settled.

3320 `paper_posted` intents are not PnL.

## Two honest hours

| Hour | Completes | Naked | Paper PnL | Best ask edge |
|---|---|---|---|---|
| 1 | 0 | 0 (tape: 1 / `-0.50`) | 0 | `-0.001` |
| 2 | 0 | 1 | `-0.20` | `-0.001` |

The completeness trade is not on the book. Stop. Do not lower `min_edge`. Do not restore still-at-bid fills. Do not go live. Task 12 stays dark.
