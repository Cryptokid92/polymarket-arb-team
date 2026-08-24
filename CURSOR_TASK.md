# Cursor review — Task 10 only

Review the Task 10 recorder / backtest / adversary commit. Do not implement Tasks 11–12.

## Run

```bash
uv run pytest tests/test_backtest.py tests/test_adversary.py tests/test_preflight.py tests/test_killswitch.py tests/test_state.py tests/test_merge.py tests/test_naked_leg.py tests/test_executor_paper.py tests/test_fee_agent.py tests/test_risk.py tests/test_hunter.py tests/test_books.py tests/test_fees.py tests/test_money.py -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not call the network in default tests.
- Do not import or construct `AsyncSecureClient`.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, or state databases.

## Check

- Replay uses recorded asks+bids+depth. Never last-trade or mid as fill price.
- `p_miss` (default 0.3) can fail the second FAK; maker fills are independent per side.
- Taker path subtracts protocol fees. Naked legs pay configurable hedge slippage.
- Report includes trades, completed_pairs, naked_incidents, net_pnl, capital_turns.
- Feeding mids instead of asks makes `detect_mid_fill` fail (detector catches the lie).
- Second ask gone before `t+latency` is not a completed pair.
- Fee-on crypto 50¢ books with a 2¢ gap are not profitable as taker.
- Hunter seeing `book[t+1]` at time `t` is a hard fail (`detect_lookahead`).
- `scripts/record_books.py` refuses to place orders and does not call the network.
- Synthetic recorded JSONL ships under `tests/fixtures/`.
