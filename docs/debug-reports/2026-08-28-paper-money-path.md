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

## Completed pairs froze at 70 (`max_open_pairs`)

The recorded hour was not halted. After 70 completed / 1 naked / 74 intents, the next 80+ maker quotes were all `max_open_pairs`. Three honest maker rests were still in memory. `poll_rests` kept them forever when a 5000-window `retain()` dropped their books (`yes is None or no is None: still.append`). `max_open_pairs` 3 is the real cap; it must not stay full of dead rests. Missing-book rests now cancel after `maker_rest_ms`. Window swap force-expires rests before retain. Do not raise `max_open_pairs`.

## Halt `hedge_incidents` (not ws_stale)

The recorded hour halted again with `halt_reason=hedge_incidents`, 3 naked maker rows, fees `0`. Makers pay 0 on the venue; this is not a missing-fee bug. The rest model treated “still at our bid” as a fill. When one book moved and the other stayed, poll_rests marked the quiet side filled and hedged it — a false naked. One-sided still-at-bid now cancels both legs. A shown take (ask through / size down) still hedges. Human Start writes `hedge_resume_ms` so evaluate does not re-trip the same three; 3 new hedges / hour still kill.

## `ws_stale` again (REST still writing)

Official subscribe dies after list/`aclose`. `watch_silence` then passed stream age into `evaluate` on the live tick, and `rest_probe_watch` wrapped `get_order_books` in a 3s `wait_for`. A slow batch looked like a dead venue while listing/stats were still live. Stream age no longer trips `ws_stale`. The probe waits for the official fetch; only a real `PublicApiError` / timeout from the client trips. Human Start still required to clear a latched halt. Do not auto-resume.

## Watch 100

`--watch-pairs` default is 100 (200 token ids). Still batched at 50. Still not the whole universe. `PIN_HOT_PAIRS` stays 8. `min_edge` / `max_open_pairs` / `LIST_SAFETY_CAP` unchanged.

## Catalog wrap (do not stop the hour)

Listing is 5000-market windows via official `next_cursor`. The hour used to `break` when the next window had the same condition ids and no further cursor — a one-page catalog, or a last-page repeat from Gamma. That looked like “it finished all books and stopped.” The loop now sets `after_cursor=None` (first page of 5000), increments `list_wraps`, and keeps watching until `--seconds`. Dashboard shows **catalog wraps**. Do not raise `LIST_SAFETY_CAP`.

## Go-live (human, later)

Task 12 stays dark. Agents never create `ALLOW_LIVE`. One positive tape replay is not two separate honest paper hours on a live venue. This host is not a live venue.
