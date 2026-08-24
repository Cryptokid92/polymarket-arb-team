# Cursor review — Task 1 only

Review the Task 1 scaffold commit. Do not implement Tasks 2–12.

## Run

```bash
uv run pytest tests/test_money.py -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, or state databases.

## Check

- README includes a not-financial-advice disclaimer and points at `.env.example`.
- Official SDK mentioned is `polymarket-client` only (`from polymarket import AsyncPublicClient, AsyncSecureClient`).
- `live_allowed` is false without `ALLOW_LIVE`, and false when `ARB_MODE=paper` even if a dated `ALLOW_LIVE` exists in a temp dir.
- Default `ARB_MODE` is paper.
- Public money helpers never use `float`.
