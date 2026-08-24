# Cursor review — Task 8 only

Review the Task 8 merge/hedge commit. Do not implement Tasks 9–12.

## Run

```bash
uv run pytest tests/test_merge.py tests/test_naked_leg.py tests/test_executor_paper.py tests/test_fee_agent.py tests/test_risk.py tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not call the network in paper merge/hedge.
- Do not import or construct `AsyncSecureClient`.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, or state databases.

## Check

- `mergeable(10, 7) == 7`.
- Paper `maybe_merge` returns 7 and never imports `AsyncSecureClient`.
- One leg 10 / other 0 after timeout → hedge sell 10 YES FAK, `incident=True`.
- Balanced fills → `hedge_plan` is None.
- Live merge raises (`Task 12`); paper stays dark.
