# Paper money path — 28 Aug 2026

Paper only. No `ALLOW_LIVE`. No live orders. Not financial advice.

Host: cloud agent box. Public API reachable. Geoblock still applies to live; paper skips geoblock. Do not treat this host as a live venue.

## Phase A — miss vs absence

Replayed the 27 Aug recorded hour (`data/paper-evidence/books.jsonl`, gitignored):

```text
uv run python scripts/backtest_tape.py --tape data/paper-evidence/books.jsonl
```

| Field | Value |
|---|---|
| events | 58_376 |
| frames | 58_295 |
| ask-gap frames (VWAP sum `<= 0.99`) | 0 |
| best ask edge | `-0.001` |
| `gt_-0.005` / `gt_-0.002` / `gt_0` / `gte_0.01` | 15_831 / 7_189 / 0 / 0 |
| `0_0.005` or better (ask walk) | 0 |
| decision | `maker_completeness` |

Same result as the live `data/paper/stats.json` snapshot (`gaps=0`, `best_edge=-0.001`, histogram empty at `0_0.005`). The closest book is one tenth of a cent short of $1. Hunt did not miss a 1-cent ask gap. CLOB asks stayed complete.

**Gate:** Phase B (pin fleeting taker gaps) is not the path. Do not lower `min_edge`. Phase C (maker completeness) is the money path.

## Phase C — maker completeness on the same tape

`run_backtest` now joins both best bids when their sum is `<= 0.99` (makers pay 0). Honest rest model; fills at the bid limit, not mid, not ask VWAP.

| Field | Value |
|---|---|
| trades | 154 |
| completed pairs | 154 |
| naked incidents | 0 |
| net pnl | `32.215` |
| capital turns | `25.42785` |
| verdict | `positive` |

`maker_quote_frames` on that tape: 23_420. Caps were not loosened. `naked_incidents` did not trip the kill switch.

This is paper EV on a recorded public tape. It is not live money. Instant both-leg (`honest=False`) is still not the money story.

## New recorded hour

Command (separate gitignored dir; does not touch the live dashboard `data/paper`):

```bash
ARB_MODE=paper uv run python scripts/paper_run.py --all-markets --seconds 3600 --record-books --data-dir data/paper-evidence-2026-08-28
```

Then:

```bash
uv run python scripts/backtest_tape.py --tape data/paper-evidence-2026-08-28/books.jsonl
uv run python scripts/report_paper.py --data-dir data/paper-evidence-2026-08-28
```

If that hour's tape is `non_positive`: stop. Do not loosen `min_edge`. Do not go live.

## Start click vs `ws_stale` re-trip

UI Start (`POST /api/control {action:start}`) clears sqlite halt when no `HALT` file is present. It does not spawn a second runner if the pid is alive. On the 28 Aug recorded hour the five maker completes happened in the first ~20s, then `ws_stale` latched. Start returned `ok` and immediately re-opened `halted=1 reason=ws_stale`.

Cause: `consider()` and the already-halted `watch_silence` tick passed `heartbeat.age_ms` into `KillSwitch.evaluate`. Official subscribe often dies after list/`aclose` while REST books still work (`book_batch_failed=0`). Stream age then exceeds `ws_stale_ms` 3000, so the next consider/tick re-trips. `stats.json` `heartbeat_ms` is the last stats write, so the dashboard can look live while the kill switch is halted.

Fix: `consider()` and the halted silence tick pass `ws_age_ms=0`. Liveness stays `watch_silence` + REST probe; `trip_dead_stream` only if that probe returns 0. After `ws_stale`, leftover window sleep wakes on human Start instead of waiting out the 60s hold. Same-dir restart keeps `completed_pairs` / maker-quote counters from `stats.json`. Caps unchanged. Task 12 stays dark.

## Go-live (human, later)

Task 12 stays dark. Agents never create `ALLOW_LIVE`. One positive tape replay is not two separate honest paper hours on a live venue. This host is not a live venue.
