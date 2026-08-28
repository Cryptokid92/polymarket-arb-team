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

Paper trading helper (not Task 12): closest-book / near-miss JSONL + stats, `record_books.py` streams official public books, honest paper fills (FAK miss / maker rest / naked hedge), pin 8 hot pairs inside `WATCH_PAIRS=100`, local `alerts.jsonl`, `scripts/backtest_tape.py`. Caps unchanged (`min_edge` 0.01, `stale_ms` 400, `LIST_SAFETY_CAP` 5000). Task 12 stays dark.

- `uv run pytest -q` — 216 passed
- Plan: `docs/plans/cursor-paper-trading-helper.md`
- Evidence: `docs/debug-reports/2026-08-27-paper-evidence.md` — 1-hour `--all-markets` finished (`listed=5000` / `universe=1546` / `gaps=0` / best walked edge `-0.001`). Same-market tape: 0 trades, verdict `non_positive`. Stop. Do not loosen `min_edge`. Task 12 stays dark.
- `ALLOW_LIVE` was not created. Live trading is not enabled. No secrets committed.

Paper money path (Milestone 13, not Task 12): Phase A telemetry + watch-while-list. 27 Aug tape has `ask_gap_frames=0` / best ask edge `-0.001` → Phase C maker completeness (bid both sides at `min_edge` 0.01). Same tape replay: `completed_pairs=154`, `naked_incidents=0`, `net_pnl=32.215`, verdict `positive`. Caps unchanged. Task 12 stays dark.

- Plan: `docs/plans/cursor-paper-money-path.md`
- Evidence: `docs/debug-reports/2026-08-28-paper-money-path.md`
- `uv run pytest -q` — 279 passed
- List-window stall: if listing the next 5000 eats the 60s dwell, swap immediately (do not open subscribe). Window 1 must not stick after the next page is already listed.
- Clean hour exited: `list_window=69`, `completed_pairs=520`, `naked_incidents=0`, paper `daily_pnl=235.690`. Tape replay OOM'd on the 1.1GB `books.jsonl` and the gitignored dir was lost. `backtest_tape.py` now streams per market. No tape verdict. Do not go live.
- `ALLOW_LIVE` was not created. Live trading is not enabled. No secrets committed.

Completeness **frozen** 28 Aug 2026. Two honest hours: hour 1 `completed=0` `daily_pnl=0`; hour 2 `completed=0` one naked `daily_pnl=-0.20`. `best_edge=-0.001`. Do not loosen caps. Do not go live. Evidence: `docs/debug-reports/2026-08-28-honest-hour.md` and `docs/debug-reports/2026-08-28-honest-hour2.md`.
