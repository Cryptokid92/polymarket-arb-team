# Paper evidence — 27 Aug 2026

Paper only. No `ALLOW_LIVE`. No live orders. Not financial advice.

Host: cloud agent box. Public API reachable. Geoblock still applies to live; paper skips geoblock. Do not treat this host as a live venue.

Command:

```bash
ARB_MODE=paper uv run python scripts/paper_run.py --all-markets --seconds 3600 --record-books --data-dir data/paper-evidence
```

`data/paper-evidence/` is gitignored. Not committed.

## Opening scan

- `markets_listed`: 5000 (safety ceiling)
- `universe`: 1546
- `gaps`: 0
- `intents` / `alerts` / `fills`: 0
- `watching`: 40
- rejects: `neg_risk` 3329, `not_accepting` 56, `seconds_delay` 68, `short_crypto_window` 1
- First closest walked edge: about `-0.05`

Process stayed up after listing and batched books. No fat-payload death. No WS Decimal crash in the opening window.

## Mid-hour (process still running)

Around minute 46–47:

- `gaps`: 0
- `best_edge`: `-0.001` (one tenth of a cent short of completeness; still below `min_edge` 0.01)
- `closest_fillable`: 5
- `closest_in_watch`: false
- `nearmiss_considers`: ~787k
- histogram: most walks `lt_-0.05`; a few thousand in `-0.01_0`; no `0_0.005` or better
- `books.jsonl`: ~43k events
- `nearmiss.jsonl`: 11 rows (new-best only; no non-negative walked edge)

Hunt did not fire. Near-miss is why the hour is not "dead": books are walked, and the closest pair never reached a 1¢ completeness gap.

Caps were not loosened.

## Honest tape backtest

First replay mixed YES from market A with NO from market B (`frames_from_events` was global). That invented 106 fake trades and −109 paper PnL. That was a lie.

Fix: group frames by `condition_id`. Same-market replay of this tape:

```text
events: 43874
trades: 0
completed pairs: 0
naked incidents: 0
net pnl: 0
verdict: non_positive
```

**Stop.** Do not loosen `min_edge`. Do not treat a silent completeness hour as a reason to build or enable Task 12.

```bash
uv run python scripts/backtest_tape.py --tape data/paper-evidence/books.jsonl
```

## Hour result

Filled when the 3600s window exits (halt reason, final histogram, whether the process stayed up).

## Task 12

Still dark. Agents did not create `ALLOW_LIVE`.
