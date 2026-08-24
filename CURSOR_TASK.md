# Cursor review — Task 9 only

Review the Task 9 kill-switch / state / preflight commit. Do not implement Tasks 10–12.

## Run

```bash
uv run pytest tests/test_preflight.py tests/test_killswitch.py tests/test_state.py tests/test_merge.py tests/test_naked_leg.py tests/test_executor_paper.py tests/test_fee_agent.py tests/test_risk.py tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not call the live geoblock network in default tests.
- Do not auto-resume after halt.
- Do not import or construct `AsyncSecureClient`.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, or state databases.

## Check

- Paper preflight succeeds without keys.
- Live preflight without `ALLOW_LIVE` fails (`tmp_path` only).
- Live + injected `{blocked: true}` refuses.
- Restore does not duplicate an open pair / client-order-id.
- Halt blocks hunter intents (`approve` sees `halted` or `allow_new_intents` is False).
- `HALT` file trips the switch.
- After halt, recovered PnL / removing trip conditions does not auto-resume. Human must `resume()` after clearing `HALT`.
- Paper halt only sets `halted=True` (live `cancel_all` is Task 12).
- No network in default tests.
