# Progress

Task 1 is done (merged `15db598`). Cursor: OK.

Task 2 is done (merged `0c890a1`). Cursor: OK.

Task 3 is done (merged `2eaac20`). Cursor: OK.

Task 4 is done (merged `b57f722`). Cursor: OK.

Task 5 is done (merged `c3fc647`). Cursor: OK.

Task 6 is done (merged `d2d2acc`). Cursor: OK.

Task 7 is done (merged `0f46af0`). Cursor: OK.

Task 8 is done (merged `13c0fa0`). Cursor: OK.

Task 9 is done (merged `b67c958`). Cursor: OK.

Task 10 is done (merged `6d51143`). Cursor: OK.

Task 11 is done: live-data paper runner that cannot place orders.

- `uv run pytest -q` — 100 passed
- Mock `list_markets` / books; pytest stays offline
- `paper_run.py` source never contains `AsyncSecureClient`
- Unreachable public API raises `PublicApiError` (no fake gaps)
- Universe filter: binary, accepting, no delay, no neg-risk, no 5/15-minute crypto windows
- `report_paper.py` prints gaps, intents, maker/taker EV, reject reasons
- README documents a 1-hour paper run
- `ALLOW_LIVE` was not created. Live trading is not enabled. No secrets committed.
- Remaining: Task 12 stays dark.

Paper dashboard (not Task 12): read-only local UI to watch paper runner logs.

- `scripts/paper_ui.py` — stdlib `http.server`, bind `127.0.0.1:8765`
- Counts from `stats.json` (written by the paper runner) or JSONL
- Run status follows `stats.json` mtime / `heartbeat_ms`, not only opening-scan JSONL timestamps
- Reject-reason breakdown, recent gaps/intents, halt from `HALT` / `state.sqlite` (read-only)
- Auto-refresh every 2s
- Offline fixture tests under `tests/fixtures/paper_ui/`
- `ALLOW_LIVE` was not created. Live trading is not enabled. No secrets committed.

Paper UI follows the runner (not Task 12): hour-5 showed stale while `paper_run` was up and rewriting `stats.json`. Last event now includes stats mtime and `heartbeat_ms`. Stale does not invent a halt.

- `uv run pytest -q` — 137 passed

Paper list-all-markets (not Task 12): walk `list_markets` pages instead of one page of `page_size=max_markets`. `--all-markets` / `--max-markets 0` uses the 5000 safety ceiling. Universe/risk caps unchanged. Subscribe only kept v1 pairs.

- `markets_listed` = all seen; `universe` = kept
- README / guide document `paper_run.py --all-markets --seconds 3600`
- Plan: `docs/plans/cursor-list-all-markets.md`
- `uv run pytest -q` — 146 passed
- `ALLOW_LIVE` was not created. Live trading is not enabled. No secrets committed.

Paper batch-books + rotate watch (not Task 12): hour-6 `--all-markets` listed 5000 / universe 1540, then one fat `get_order_books` died (`Payload exceeds the limit`). REST books now batch (50 token ids). Watch 40 pairs (80 tokens); rotate remaining every 90s. Failed batch logs and continues. `LIST_SAFETY_CAP` stays 5000. Universe/risk caps unchanged.

- Plan: `docs/plans/cursor-batch-books-rotate.md`
- Debug: `docs/debug-reports/2026-08-24-hour6-payload-limit.md`
- Flags: `--book-batch-size`, `--watch-pairs`, `--watch-rotate-s`
- `uv run pytest -q` — 158 passed
- `ALLOW_LIVE` was not created. Live trading is not enabled. No secrets committed.

Paper $500 bankroll + dashboard controls (not Task 12): paper-fill both legs at VWAPs, settle $1/share, persist bankroll/`daily_pnl`/fills. Local Start/Stop pause or exec `paper_run`. Watch-rotate slider 10–120s. Not real money. No `ALLOW_LIVE`.

- `uv run pytest -q` — 185 passed
- Plan: `docs/plans/cursor-paper-bankroll-pnl.md`

Paper trading helper (not Task 12): closest-book / near-miss JSONL + stats, `record_books.py` streams official public books, honest paper fills (FAK miss / maker rest / naked hedge), pin 8 hot pairs inside `WATCH_PAIRS=40`, local `alerts.jsonl`, `scripts/backtest_tape.py`. Caps unchanged (`min_edge` 0.01, `stale_ms` 400, `LIST_SAFETY_CAP` 5000). Task 12 stays dark.

- `uv run pytest -q` — 215 passed
- Plan: `docs/plans/cursor-paper-trading-helper.md`
- Evidence: `docs/debug-reports/2026-08-27-paper-evidence.md`
- `ALLOW_LIVE` was not created. Live trading is not enabled. No secrets committed.
