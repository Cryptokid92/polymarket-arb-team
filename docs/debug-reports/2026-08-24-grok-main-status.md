# Grok — current main status

Date: 2026-08-24
Who: Grok Build, paper-only inspection of `origin/main`
SHA: `e761264d2c816103de655632ea6f65d2287eed7d`
Tip: Merge pull request #17 (`cursor/quiet-ws-stale-e50a`)
pytest: `uv run pytest -q` → **133 passed, 0 failed** (3.41s)

Paper only. No `ALLOW_LIVE`. No live orders. This host is not a live venue.

I did not start a second runner. Hour-5 was already up.

## Working

The paper pipeline on this SHA is real, and it is running.

| Piece | Evidence |
|---|---|
| List markets | Public API listed **80** (`--max-markets 80`) |
| Universe filter | **78** dropped as `neg_risk`; **2** kept |
| Books | REST snapshot then WS/poll. Hour-5 process has sockets open. `stats.json` still rewritten after the first scan |
| Hunter | Wired. **0** gaps written |
| Risk | Wired in code and tests. Hour-5 has no hunter hits, so no risk rows |
| Fees / fee agent | Wired in code and tests. No intents, so not exercised on this scan |
| Paper executor | `PaperBroker` JSONL only. No `intents.jsonl` this hour (nothing to post) |
| Kill switch + sqlite | Hour-5 `meta` empty: **not halted**, no `halt_reason`. No `HALT` file |
| UI | `scripts/paper_ui.py` on `127.0.0.1:8765`, banner **PAPER MODE. Not live. Not financial advice.** Counts match the files |

Live hour-5 processes (started 11:11, still alive ~4 minutes later; `--seconds 3600`):

- `ARB_MODE=paper uv run python -u scripts/paper_run.py --seconds 3600 --max-markets 80 --data-dir data/paper-hour5`
- `uv run python scripts/paper_ui.py --data-dir data/paper-hour5 --port 8765`

Hour-5 files (`data/paper-hour5/`, gitignored, not deleted):

```
{"markets_listed": 80, "universe": 2, "gaps": 0, "intents": 0, "rejects": 78, "reject_reasons": {"neg_risk": 78}}
```

- `rejects.jsonl`: 78 lines, every `reason` is `neg_risk`
- no `gaps.jsonl`, no `intents.jsonl`
- `state.sqlite` tables empty (no halt, no fills, no hedge incidents)
- runner stdout (`/workspace/paper-hour5.log`) empty — no crash print

Fixes already on this SHA (from earlier hours, not re-broken here):

- Hour-1: kill switch used CLOB book age as WS age → `ws_stale`. Fixed `42e4384`.
- Hour-2: WS `min_order_size=None` → `str("None")` → Decimal crash, process exit 1. Fixed PR #15 / `511426c`.
- Hour-4: quiet live WS treated as dead socket → `halted=1`, `halt_reason=ws_stale` while the process stayed up. Fixed PR #17, this HEAD. Hour-5 has **not** tripped after several minutes of quiet books (hour-4 died on that within the same window).

Tests cover list → filter → hunt → risk → fees → paper execute, plus the three halt/crash cases above. `LiveBroker` still refuses without the human date file, and even with it the live SDK path is not implemented.

## Not working / still broken

- **Task 12 is dark.** Live path is not built. `LiveBroker` raises. Live merge / `cancel_all` are not here. Do not enable live. Do not create `ALLOW_LIVE`.
- **This host is geoblocked for live (US/AZ).** Paper skips geoblock. Public books work. Do not treat this box as a live venue.
- **Almost all listed markets are neg-risk.** First page of 80 → universe **2**. Completeness arb only runs on binary YES/NO. Tiny universe.
- **No gaps seen yet.** Hour-1 through hour-5 scans: listed 80, universe 2, gaps 0, intents 0. Same shape as the earlier paper-scans report.
- **No paper PnL.** The networked runner logs intents and bumps `open_pairs`. It does not simulate fills, merge, or PnL. I am not claiming PnL. There is none to claim.
- **Dashboard says `stale` while the runner is alive.** UI last-event uses JSONL timestamps (`rejects.jsonl` from the first scan at 11:11). It does not treat a `stats.json` rewrite as a new event. So the page can show `stale` / “last event ~4m ago” even though the process is up, not halted, and still rewriting stats. That is a dashboard heuristic, not a kill-switch halt.
- **Hour-5 is still in flight.** I inspected minutes into a 3600s run. I did not wait for the hour to finish. Counts above are that snapshot, not an end-of-hour report.

What this is not: live trading, a filled book, or a PnL number. The paper loop lists, filters, watches two books, and has not found a completeness gap.
