# Honest paper hour — 28 Aug 2026

Paper only. No `ALLOW_LIVE`. No live orders. Not financial advice.

Host: Windows. PR 31 fill and fee contracts (`fix/choose-intent-and-tape-fill`). Shown-take maker rests. Hunt is `taker_fak` or skip. Still-at-bid does not fill.

Command:

```bash
ARB_MODE=paper uv run python scripts/paper_run.py --all-markets --seconds 3600 --record-books
```

Data dir `data/paper/` is gitignored. Do not commit JSONL, sqlite, or keys.

## Runner line

Runtime 3701 s. Exit 0.

```text
paper_run done: listed=5000 universe=39 gaps=0 maker_quotes=10946 intents=2617 completed=0 rejects={'neg_risk': 92439, 'seconds_delay': 106335, 'not_accepting': 160, 'max_open_pairs': 7783, 'book_batch_failed': 17, 'short_crypto_window': 3111} bankroll=500 daily_pnl=0
```

Websocket printed `WebSocket heartbeat stale; closing` on window swaps. REST books kept walking. No `ws_stale` halt in sqlite. Bankroll never left 500.

## Final stats.json

| Field | Value |
|---|---|
| markets_listed | 5000 |
| universe (end window) | 39 |
| listed_unique | 186598 |
| universe_unique | 13781 |
| walked_unique | 13766 |
| list_window | 45 |
| list_wraps | 1 |
| list_empty_windows | 8 |
| gaps | 0 |
| maker_quotes | 10946 |
| intents / alerts | 2617 / 2617 |
| fills | 0 |
| completed_pairs | 0 |
| naked_incidents | 0 |
| bankroll | 500 |
| daily_pnl | 0 |
| best_edge | `-0.001` |
| closest_fillable | 320 |
| closest_in_watch | false |
| closest_book_age_ms | 186632 |
| nearmiss_considers | 352215 |
| gt_0 / gte_0.01 | 0 / 0 |
| max_edge_window | `-0.0048068` |

`fills.jsonl` was never created. `gaps.jsonl` was never created. Intents are `maker_gtc` / `paper_posted`. That is not PnL.

Ask histogram has no `0_0.005` or better bucket. Hunt did not miss a 1¢ take. Asks stayed complete to a tenth of a cent.

## Same books, two fill models

Mid-hour snapshot of this run's `books.jsonl`, streamed through `scripts/backtest_tape.py`:

| Engine | Ask-gap frames | Maker-quote frames | Completed pairs | Net PnL | Verdict |
|---|---|---|---|---|---|
| PR 31 shown-take | 0 | ~37k | 0 | 0 | non_positive |
| PR 30 still-at-bid | 0 | ~37k | 2568 | 1442.310 | positive |

Quiet 0.49/0.50 synthetic book: PR 30 completed 3 pairs / `1.20`. PR 31 completed 0.

The PR 30 number credits rests because the bid was still there after 400 ms. A real CLOB does not pay that. Do not restore it. Do not treat `+1442` as a live go.

Full-file replay (`uv run python scripts/backtest_tape.py --tape data/paper/books.jsonl`, 504 s). Verdict `non_positive`. PR 34 makes this CLI exit 1.

```text
paper tape edges (miss vs absence)
  frames: 517304
  ask-gap frames (VWAP sum <= 0.99): 0
  maker-quote frames: 263784
  best ask edge: 0.00110625
  decision: maker_completeness
  thresholds:
    gt_-0.005: 25747
    gt_-0.002: 6413
    gt_0: 1
    gte_0.01: 0
  edge histogram:
    -0.01_0: 82954
    -0.02_-0.01: 74096
    -0.05_-0.02: 118077
    0_0.005: 1
    lt_-0.05: 223545
    none: 18631
  phase: C — asks stay complete. Maker completeness at min_edge 0.01.
paper tape backtest
  events: 522034
  trades: 1
  completed pairs: 0
  naked incidents: 1
  net pnl: -0.50
  capital turns: 0.0775
  verdict: non_positive
  stop: net EV is not positive. Do not loosen risk. Do not go live.
```

One reconstructed frame had ask edge `0.0011` (histogram `0_0.005: 1`). That is below `min_edge` 0.01, so hunt stayed silent (`ask_gap_frames=0`, `gte_0.01=0`). The runner's live `best_edge=-0.001` is the same story at a tenth of a cent.

The one tape trade is a shown-take on one maker rest, second leg missed, hedge. `completed_pairs=0`, `naked_incidents=1`, `net_pnl=-0.50`. That is a real CLOB queue, not a bug. Do not loosen `min_edge`. Do not treat the PR 30 `+1442` as the same hour.

PR 34 (`fix/tape-fail-closed`) returns 1 on `non_positive` and on a missing tape. A missing tape is not a pass.

## Caps

Unchanged. `min_edge` 0.01. `max_gap` 0.08. `stale_ms` 400. `max_notional_per_trade` 25. `max_open_pairs` 3. Do not lower `min_edge` to harvest `-0.001`. That is buying a complete book.

## Task 12

Stays dark. One honest hour with `net_pnl=0` is not a live go. Two honest hours with `net_pnl > 0` after fees, `p_miss`, and shown takes are still required before a human even considers it. Agents do not create `ALLOW_LIVE`.
