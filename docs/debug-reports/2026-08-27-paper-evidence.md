# Paper evidence — 27 Aug 2026

Paper only. No `ALLOW_LIVE`. No live orders. Not financial advice.

Host: cloud agent box. Public API reachable. Geoblock still applies to live; paper skips geoblock. Do not treat this host as a live venue.

Command:

```bash
ARB_MODE=paper uv run python scripts/paper_run.py --all-markets --seconds 3600 --record-books --data-dir data/paper-evidence
```

`data/paper-evidence/` is gitignored. Not committed.

## Hour result (final)

Process reached `paper_run done`. Pid file cleared. No fat-payload death. No WS Decimal crash.

```text
listed=5000 universe=1546 gaps=0 intents=0
rejects={'neg_risk': 3329, 'not_accepting': 56, 'seconds_delay': 68, 'short_crypto_window': 1}
bankroll=500 daily_pnl=0
```

From final `stats.json` / `report_paper.py`:

| Field | Value |
|---|---|
| markets_listed | 5000 |
| universe | 1546 |
| watching | 40 |
| gaps | 0 |
| intents / alerts / fills | 0 |
| completed_pairs / naked_incidents | 0 |
| best_edge | `-0.001` |
| closest_fillable | 5 |
| closest_in_watch | false |
| closest_thin | false |
| nearmiss_considers | 1_078_540 |
| books.jsonl events | 58_376 |
| nearmiss.jsonl rows | 11 (new-best only) |

Edge histogram (walked asks):

| Bucket | Count |
|---|---|
| `lt_-0.05` | 1_058_353 |
| `-0.05_-0.02` | 9_736 |
| `-0.02_-0.01` | 2_064 |
| `-0.01_0` | 5_624 |
| `0_0.005` or better | 0 |
| `none` (thin) | 2_763 |

Closest pair: `0xe70dc5791fd703624bdd33fbdd6c4374bf51723c4c5e2fb88ee87857dc72d762` (not in the watch slice). One tenth of a cent short of completeness. Still below `min_edge` 0.01. Hunt did not fire.

Caps were not loosened.

## Halt at exit

sqlite: `halted=1`, `halt_reason=ws_stale`. stderr: `WebSocket heartbeat stale; closing`. There was no `HALT` file.

The process still printed `paper_run done` after the 3600s window. This is an end-of-stream / quiet-socket close, not a mid-hour Decimal crash. Do **not** raise `ws_stale_ms`. Quote staleness stays `stale_ms=400`.

## Honest tape backtest

`frames_from_events` groups by `condition_id`. YES from one market is never hunted against NO from another.

```text
events: 58376
trades: 0
completed pairs: 0
naked incidents: 0
net pnl: 0
capital turns: 0
verdict: non_positive
stop: net EV is not positive. Do not loosen risk. Do not go live.
```

```bash
uv run python scripts/report_paper.py --data-dir data/paper-evidence
uv run python scripts/backtest_tape.py --tape data/paper-evidence/books.jsonl
```

**Stop.** Do not loosen `min_edge`. Do not treat a silent completeness hour as a reason to build or enable Task 12.

## Task 12

Still dark. Agents did not create `ALLOW_LIVE`.
