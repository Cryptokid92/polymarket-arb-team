# Shared law

This is a **paper-first** public repo. Read this before writing code.

## Mode and live gate

- Paper is the default. `ARB_MODE` defaults to `paper`.
- Never create `ALLOW_LIVE`. Never place live orders. Never commit secrets, `.env`, keys, paper fills, or state databases.
- `LIVE_TRADING` is allowed only when **both** are true:
  1. `ARB_MODE=live`
  2. A **human-created** `ALLOW_LIVE` file exists in the project root and contains **today's ISO date** (`YYYY-MM-DD`)
- Agents must not enable live trading. Cursor reviews must never flip the live gate.

## Money, fees, execution

- All money is `Decimal`. Never use `float` for prices, sizes, notional, edge, or PnL.
- Makers pay 0. Never hardcode fees; read them from the venue / official SDK.
- A half-filled arb is worse than no trade. Abort rather than leave a naked leg.

## SDK and hot path

- Official client only: `polymarket-client`.
- Import path: `from polymarket import AsyncPublicClient, AsyncSecureClient`.
- No LLM in the hot path (quotes, edge, sizing, orders, hedge, cancel).
- Do not scrape influencer wallets.

## Team protocol

- One writer at a time.
- Grok implements. Cursor reviews.
- Implementer: TDD, one task, one commit series, paper only.
- Reviewer: spec and quality only; never enable live.
