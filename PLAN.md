# Plan (paper-only)

Not financial advice. No guaranteed PnL. Live trading is out of scope for every task listed here.

## Task 1 — Scaffold — done

Repo layout, MIT license, paper-default `Settings`, Decimal money helpers, dual live gate (`ARB_MODE=live` **and** a human-created `ALLOW_LIVE` dated today). Tests: `uv run pytest tests/test_money.py -q`.

## Remaining paper-only tasks

Later specialists land these one at a time. Do not enable live. Do not put an LLM in the hot path.

2. Official `polymarket-client` wrapper (`AsyncPublicClient` / `AsyncSecureClient` imports only). Read-only paper wiring. No live orders.
3. Discover binary completeness pairs (YES + NO on the same event) from public market data.
4. Quote / book snapshots with `STALE_MS` rejection.
5. Decimal edge and gap (`MIN_EDGE`, `MAX_GAP`). Makers pay 0; never hardcode fees.
6. Risk gates from settings: `MAX_NOTIONAL_PER_TRADE_PUSD`, `MAX_DAILY_LOSS_PUSD`, `MAX_OPEN_PAIRS`.
7. Paper matching / simulated fills. Persist only under gitignored `data/`.
8. Two-leg pair executor with `HEDGE_TIMEOUT_MS`. A half-filled arb is worse than no trade.
9. WebSocket market data with `WS_STALE_MS`.
10. Local paper state (sqlite/files under `data/`, never committed).
11. Paper runner: `HALT` file, daily-loss trip, CLI. Still paper-only.

Task 12+ (any live path) is not in this plan.
