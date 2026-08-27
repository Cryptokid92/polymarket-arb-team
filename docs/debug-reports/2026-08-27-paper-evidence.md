# Paper evidence — 27 Aug 2026

Paper only. No `ALLOW_LIVE`. No live orders. Not financial advice.

Host: cloud agent box. Public API reachable. Geoblock still applies to live; paper skips geoblock. Do not treat this host as a live venue.

Command:

```bash
ARB_MODE=paper uv run python scripts/paper_run.py --all-markets --seconds 3600 --record-books --data-dir data/paper-evidence
```

## Opening scan (first seconds)

From `data/paper-evidence/stats.json` (gitignored, not committed):

- `markets_listed`: 5000 (safety ceiling)
- `universe`: 1546
- `gaps`: 0
- `intents`: 0
- `alerts`: 0
- `fills` / `completed_pairs` / `naked_incidents`: 0
- `watching`: 40
- rejects: `neg_risk` 3329, `not_accepting` 56, `seconds_delay` 68, `short_crypto_window` 1 (3454 total)
- `best_edge`: about `-0.05` (five cents short of completeness on walked VWAPs)
- `closest_in_watch`: false (the closest pair was not in the first 40)
- `nearmiss_considers`: 900+ during the first book batches; histogram `lt_-0.05`
- `books.jsonl` written (`--record-books`)

Hunt did not fire. Near-miss telemetry is why the run is not "dead": books are walked, and the closest pair is still ~5¢ away from `min_edge` 0.01.

Caps were not loosened.

## Hour result

Filled in after the 3600s window ends. See the same `stats.json` / `report_paper.py` / `backtest_tape.py` output.

## Tape backtest

```bash
uv run python scripts/backtest_tape.py --tape data/paper-evidence/books.jsonl
```

If verdict is `non_positive` or `no_tape`: **stop**. Do not loosen `min_edge`. Do not implement Task 12 on the back of a silent hour.

## Task 12

Still dark. Agents did not create `ALLOW_LIVE`.
