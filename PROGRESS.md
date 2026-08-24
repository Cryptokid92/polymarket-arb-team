# Progress

Task 1 is done (merged `15db598`). Cursor: OK.

Task 2 is done (merged `0c890a1`). Cursor: OK.

Task 3 is done (merged `2eaac20`). Cursor: OK.

Task 4 is done (merged `b57f722`). Cursor: OK.

Task 5 is done (merged `c3fc647`). Cursor: OK.

Task 6 is done (merged `d2d2acc`). Cursor: OK.

Task 7 is done (merged `0f46af0`). Cursor: OK.

Task 8 is done (merged `13c0fa0`). Cursor: OK.

Task 9 is done: crash-safe state, paper preflight, manual-resume kill switch.

- `uv run pytest tests/test_preflight.py tests/test_killswitch.py tests/test_state.py …` — 79 passed
- Restore does not duplicate an open pair / client-order-id
- Halt blocks hunter intents (`approve` sees `halted`; `allow_new_intents` is False)
- `HALT` file trips the switch; recovered PnL does not auto-resume
- Paper preflight ok without secrets
- Live preflight without `ALLOW_LIVE` fails on `tmp_path` only
- Geoblock is injected; default tests do not use the network
- `ALLOW_LIVE` was not created. Live trading is not enabled. No secrets committed.
- Remaining: paper-only Tasks 10–11. Task 12 stays dark.
