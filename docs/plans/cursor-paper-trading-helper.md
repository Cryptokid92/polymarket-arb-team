# Cursor plan — paper trading helper (not Task 12)

Date: 2026-08-27
Agent: implementer
Starting ref: `main` (`f71a412`) after paper bankroll (#22)

Paper only. Never create `ALLOW_LIVE`. Never place live orders. Do not loosen `stale_ms`, `min_edge`, `max_gap`, `max_notional_per_trade`, `WATCH_PAIRS`, `LIST_SAFETY_CAP`.

## What landed

1. **Near-miss telemetry.** Every consider walks ask depth. `raw_edge` is recorded only when both sides fill `min_size`. Thin books are `none`, not a fake top-of-book edge. Rolling best + histogram in `stats.json`. JSONL only for a new best or a walked non-negative edge.
2. **Recorder.** `scripts/record_books.py` uses `AsyncPublicClient` and writes watch-slice books. `paper_run --record-books` dumps `data-dir/books.jsonl`. Compatible with Task 10 `frames_from_events`.
3. **Honest paper fills.** `PaperLedger(honest=True)` (networked runner default): taker FAK may miss the second leg (`p_miss` 0.3) and hedge leftover; maker GTC rests until timeout then fill/cancel/hedge. Instant both-leg fill remains the unit-test default (`honest=False`).
4. **Hot watch.** Pin up to 8 highest walked-edge pairs inside the existing 40. Always leave a rotate slot when universe > watch. Do not raise `WATCH_PAIRS`.
5. **Alerts.** When `choose_intent` succeeds, write `alerts.jsonl` and show it on the local dashboard. No webhook. No secure client.
6. **Tape backtest.** `scripts/backtest_tape.py` replays recorded books. If net EV is not positive: stop. Do not loosen risk. Do not go live.

## Caps (must still hold)

- `min_edge` 0.01, `max_gap` 0.08, `stale_ms` 400, `ws_stale_ms` 3000
- `max_notional_per_trade` 25, `WATCH_PAIRS` 40, `PIN_HOT_PAIRS` 8, `LIST_SAFETY_CAP` 5000, `BOOK_BATCH_SIZE` 50

## Task 12

Stays dark. `LiveBroker` still raises. Agents never create `ALLOW_LIVE`.
