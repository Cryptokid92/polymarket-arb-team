# Cursor review — paper dashboard only (not Task 12)

Review the read-only paper UI. Do **not** implement Task 12. Do **not** create `ALLOW_LIVE`.

## Run

```bash
uv run pytest -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not construct `AsyncSecureClient`.
- Do not call the live network in default tests.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, `data/`, sqlite, or paper JSONL with account data.

## Check — paper UI

- `scripts/paper_ui.py` uses stdlib `http.server` + HTML (no new web deps).
- Read-only: GET only; POST is 405.
- Binds `127.0.0.1` (default port 8765). `--data-dir` and `--port` flags.
- Banner: `PAPER MODE. Not live. Not financial advice.`
- Missing JSONL → zeros / empty lists. Does not invent trades.
- Shows run status (last log mtime / last event age), counts, reject reasons, recent gaps, recent intents, halt flag.
- Auto-refresh every 2s.
- Halt is inferred read-only from `HALT` and/or `state.sqlite`.
- Source never contains `AsyncSecureClient`. `--place-orders` is refused.

## Check — live gate

- `live_allowed()` is still false without a human `ALLOW_LIVE` dated today, and false when `ARB_MODE=paper`.
- `LiveBroker` still raises without the dual gate.
- Paper UI / runner cannot place live orders.
- No `ALLOW_LIVE` file in the repo.

## Check — docs

- README documents `paper_run.py --seconds 3600` and `paper_ui.py --data-dir data/paper` in two terminals.
- PLAN / PROGRESS mark this as a paper viz task, not Task 12.
