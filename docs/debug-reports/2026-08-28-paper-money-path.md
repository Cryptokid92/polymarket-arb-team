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

## List window stuck on 1

A clean 1-hour run listed the next 5000 (`listed_unique` 9956, `universe_unique` 3078) but `list_window` stayed 1 and `walked_unique` froze at 1545. `list_cursor.json` already had the next-page cursor. Listing 50 official pages plus the opening snapshot ate the 60s dwell; `run_watch_until` still opened official subscribe. `asyncio.wait_for` on that socket waits for aclose after cancel; official aclose often swallows `CancelledError`, so the swap never ran.

Fix: if leftover hold is 0 after listing, apply the queued window immediately. Do not open subscribe. The dwell timer is created before consume. `consume_until` uses `asyncio.wait` + sleep, not `wait_for`. A live subscribe flood also returns when the dwell ends (`now >= stop_at`), not only when `--seconds` is up. Caps unchanged. Task 12 stays dark.

## Catalog wrap (do not stop the hour)

Listing is 5000-market windows via official `next_cursor`. The hour used to `break` when the next window had the same condition ids and no further cursor — a one-page catalog, or a last-page repeat from Gamma. That looked like “it finished all books and stopped.” The loop now sets `after_cursor=None` (first page of 5000), increments `list_wraps`, and keeps watching until `--seconds`. Dashboard shows **catalog wraps**. Do not raise `LIST_SAFETY_CAP`.

## Clean hour (data/paper-hour-20260828)

Command:

```bash
ARB_MODE=paper python scripts/paper_run.py --all-markets --seconds 3600 --record-books --watch-pairs 100 --data-dir data/paper-hour-20260828
```

Started 09:50:36 UTC after the list-window swap fix. `paper_run done` at ~10:50 UTC. Not halted. `list_window` ended at **69** (`list_wraps=1`). Window 1 did not stick.

Live paper counters at exit (from `stats.json` / stdout; gitignored dir):

| Field | Value |
|---|---|
| completed pairs | 520 |
| fills | 520 |
| intents | 533 |
| maker quotes | 934 |
| gaps | 0 |
| naked incidents | 0 |
| bankroll | `735.690` |
| daily_pnl | `235.690` |
| listed unique | 186_509 |
| universe unique | 13_598 |
| walked unique | 13_582 |
| best ask edge | `-0.001` |
| `gt_0` / `gte_0.01` | 0 / 0 |
| max_open_pairs rejects | 259 |
| hedge incidents | 0 |

`report_paper.py` on that dir matched: 0 taker gaps, Phase C maker path, 0 naked. Paper $500 is not real money.

### Tape replay OOM — file gone

`books.jsonl` was 1.1 GB / 984_618 events. `load_jsonl` slurped the whole file; RSS hit ~14 GB and the kernel OOM-killed other processes. After that, `data/` and `.venv` were gone. `backtest_tape.py --tape data/paper-hour-20260828/books.jsonl` now returns `no_tape`.

Do **not** treat the live `daily_pnl` as a tape verdict. Without the recorded books, Phase A/C replay is not re-runnable. Do not loosen `min_edge`. Do not go live. Task 12 stays dark.

`backtest_tape.py` now streams one `condition_id` at a time (`replay_tape_path`) so the next hour tape does not load 1 GB of JSON into RAM.

## Working-bot backup (scan loop only — not the paper PnL)

Two separate things. Do not mix them.

**1. What this repo does if you put keys in `.env`.** Nothing live. `paper_run.py` only builds `AsyncPublicClient`. It never constructs a trading client. `LiveBroker` still raises `live SDK calls are not implemented` even after `ARB_MODE=live` and a dated `ALLOW_LIVE` file. Task 12 was never built. Connecting an account does not turn PR 30 into a live bot.

**2. What those paper “wins” would mean if the same orders actually hit the CLOB.** They would not collect. The ledger marks a rest as filled because the bid was still there after `maker_rest_ms` (400 ms default; this runner used `hedge_timeout_ms`). That is not a seller hitting your GTC.

On a real book:

- You post GTC buys at the bid (example: 49¢ YES and 49¢ NO).
- Most of the time nobody sells into you. The quotes sit. You earn $0. That is what PR 31 looks like.
- When you do get filled, it is often one side. You are long YES or long NO, not a complete pair. That is a directional bet plus a hedge, usually a loss after slippage. The kill switch exists because three of those in an hour is supposed to halt you.
- You get filled more when the market is moving against that bid (adverse selection). PR 30’s model is the opposite: it fills both legs whenever the quote is still pretty.

The other PR 30 lie is worse if hunt ever fires. `choose_intent` prefers `maker_gtc` with zero fees whenever maker EV is positive, so a 3¢ ask gap (asks 0.55 and 0.42) can be booked as a free rest. A live buy at those limits is a take. You pay taker fees. Paper can show about +$2.40; after protocol fees that take can be negative.

| Paper PR 30 | Real book |
|---|---|
| Thousands of completed pairs and a large `daily_pnl` (example local board: 2568 pairs, +$1442; this VM hour: 470 pairs, +$257.775) | Almost all unfilled rests |
| Both legs fill because bids still show | One leg fills, or neither |
| Maker fees 0 on an ask-priced “GTC” | You are a taker if the limit is at the ask |

PR 31 (`fix/choose-intent-and-tape-fill`) looks “unprofitable” because it stopped writing those fake fills. A live account would look like PR 31, plus naked-leg risk PR 30 never charged.

Do **not** collect PR 30 paper PnL. Do not create `ALLOW_LIVE`. Do not point this at a funded wallet. The paper $500 is not a backtest of an account.

What *was* worth keeping from this VM is the **scan loop** on GitHub `main` `582d66a` (PR #30 squash): watch 100, 1s rotate, 60s 5000-windows, catalog wrap, leftover skip, `ws_age_ms=0`. That tree matches this VM (`f143762` diffs empty). The hour files under `/opt/cursor/artifacts/backups/paper-working-bot-20260828-1133/` are a paper-ledger snapshot only.

This VM hour (11:33–12:33 UTC, no `--record-books`):

| Field | Value |
|---|---|
| completed pairs | 470 (paper ledger, not CLOB) |
| daily_pnl | `257.775` (paper ledger, not CLOB) |
| gaps | 0 |
| naked incidents | 0 |
| list_window / wraps | 66 / 1 |
| listed / walked unique | 186_608 / 13_755 |
| watching | 100 |
| best ask edge | `-0.001` |
| `gt_0` / `gte_0.01` | 0 / 0 |

There is no `books.jsonl` for this hour. Do not treat `daily_pnl` as a tape verdict. Do not loosen `min_edge`. Task 12 stays dark.

## Go-live (human, later)

Task 12 stays dark. Agents never create `ALLOW_LIVE`. Keys in `.env` do not place orders. One paper `daily_pnl` is not a CLOB account. This host is not a live venue. A missing tape is not a pass.
