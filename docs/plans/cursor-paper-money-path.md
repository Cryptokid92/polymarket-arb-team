# Cursor plan — paper money path (Milestone 13, not Task 12)

Date: 2026-08-28
Agent: implementer
Starting ref: `cursor/watch-rotate-1s-7a61` (`cf30eaf`)

Paper only. Never create `ALLOW_LIVE`. Never place live orders. Do not loosen `min_edge` 0.01, `max_gap` 0.08, `stale_ms` 400, `WATCH_PAIRS` 40, or `LIST_SAFETY_CAP` 5000. Do not implement Task 12.

Not financial advice. Paper $500 is not real money. This host is geoblocked for live.

## Why the bot was not printing

The taker completeness trade was not there. Hunt only fires when both ask VWAPs sum to `<= 0.99`. Live and recorded hours stayed at `best_edge=-0.001` with an empty `0_0.005` histogram bucket. Fee agent never saw a gap, so maker GTC never posted. Coverage work (cycle 5000 / 1s REST rotate) increased unique listed/walked. It did not create a 1-cent ask gap.

## What landed

1. **Phase A telemetry.** `NearMiss.window_id`. Tracker counts considers with `raw_edge > -0.005`, `> -0.002`, `> 0`, `>= 0.01` (still do not hunt below 0.01). Persist `max_edge_window` per list window. JSONL tags `in_watch`, `book_age_ms`, `window_id`.
2. **Watch while the next 5000 lists.** REST-walk the current 40-pair slice during `list_markets`. Full-universe rotate REST stays skipped while listing. The watch is not silent for 40–70s.
3. **Miss vs absence gate.** `analyze_tape_edges` + `scripts/backtest_tape.py` print ask-gap frames vs maker-quote frames. Aug 27 evidence hour: `ask_gap_frames=0`, best ask edge `-0.001`, decision `maker_completeness`. Phase B (pin fleeting taker gaps) is not the path. Do not lower `min_edge`.
4. **Phase C maker completeness.** `maker_complete_quotes` joins both best bids when `yes_bid + no_bid <= 0.99`, sizes from best-bid depth on the `min_order_size` grid, clips to `max_notional_per_trade` 25, refuses thin / stale / `max_gap`. Synthetic ask levels at the bid prices so `approve()` can re-walk. Second intent source; does not go through ask-`hunt()`. Hunt still ignores bids.
5. **Honest paper rests.** Existing `PaperLedger` maker GTC rest / timeout / hedge. `has_rest` + `resting_pairs` so `max_open_pairs` is not a no-op. Half-fill hedges the naked leg. 3 hedge incidents / hour still kill. Alerts stay local JSONL.
6. **Tape replay.** `run_backtest` tries maker completeness when hunt is silent. Maker fills are at the bid limit (`fill_source=bid`), not ask VWAP and not mid. Aug 27 evidence tape: `completed_pairs=154`, `naked_incidents=0`, `net_pnl=32.215`, verdict `positive`. Task 12 stays dark.

## Caps (must still hold)

- `min_edge` 0.01, `max_gap` 0.08, `stale_ms` 400, `ws_stale_ms` 3000
- `max_notional_per_trade` 25, `WATCH_PAIRS` 40, `PIN_HOT_PAIRS` 8, `LIST_SAFETY_CAP` 5000, `BOOK_BATCH_SIZE` 50

## Task 12

Stays dark. `paper_run.py` still has no `AsyncSecureClient`. Agents never create `ALLOW_LIVE`. This cloud host is not a live venue.

A human may consider live only after two separate honest paper hours (or equivalent tape) with `net_pnl > 0` after fees, `p_miss`, and hedges; `naked_incidents` under the kill threshold; caps unchanged; a non-geoblocked venue; and a human-written `ALLOW_LIVE` dated today with `ARB_MODE=live`. First live notional stays 25. Until then: paper $500 on the dashboard is the only "PnL".
