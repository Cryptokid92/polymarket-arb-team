# Cursor review — Task 11 only (last paper task)

Review the paper runner and the live gate. Do **not** implement Task 12. Do **not** create `ALLOW_LIVE`.

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
- Do not commit secrets, `.env`, keys, paper fills, or state databases.

## Check — paper runner

- `scripts/paper_run.py` imports `from polymarket import AsyncPublicClient` only.
- Source never contains `AsyncSecureClient`.
- `list_markets(closed=False)` (or the installed equivalent).
- v1 universe: binary YES/NO, accepting orders, no `seconds_delay`, no neg-risk, no 5/15-minute crypto windows.
- Subscribe via official SDK when available; otherwise poll `get_order_books` (document drift in README).
- Pipeline is hunt → risk → fee → paper executor.
- Writes gitignored `data/paper/intents.jsonl` and `data/paper/gaps.jsonl`.
- Unreachable public API raises a clear error and does not fake gaps.
- `--place-orders` is refused. `ARB_MODE=live` is refused.
- Tests mock the public client (offline).

## Check — live gate

- `live_allowed()` is still false without a human `ALLOW_LIVE` dated today, and false when `ARB_MODE=paper`.
- `LiveBroker` still raises without the dual gate.
- Paper runner cannot place live orders.
- No `ALLOW_LIVE` file in the repo.

## Check — report / README

- `scripts/report_paper.py` prints gaps seen, intents approved, estimated maker EV, estimated taker EV, reject reasons.
- README documents a 1-hour paper run and `report_paper.py`.
