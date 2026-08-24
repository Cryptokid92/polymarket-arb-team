# Cursor review — Task 7 only

Review the Task 7 paper-executor commit. Do not implement Tasks 8–12.

## Run

```bash
uv run pytest tests/test_executor_paper.py tests/test_fee_agent.py tests/test_risk.py tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE` in the repo.
- Do not place live orders.
- Do not construct a real `AsyncSecureClient` in paper tests.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, or state databases.

## Check

- `PaperBroker` writes one JSONL record per pair to an injectable path (`tmp_path`).
- Paper path never imports or calls `AsyncSecureClient`.
- `LiveBroker` raises without `ALLOW_LIVE`, and still raises in paper mode even if a temp `ALLOW_LIVE` exists.
- `run_pipeline` on `gap_3c` + healthy flags + crypto fees → `maker_gtc` (risk may clip size).
- `run_pipeline` on `no_gap.json` → None.
- `data/` is gitignored.
