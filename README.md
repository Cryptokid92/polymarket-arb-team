# polymarket-arb-team

Paper-first completeness arbitrage bot for [Polymarket](https://polymarket.com).

This repository scaffolds a **paper-mode** specialist team that looks for completeness (YES + NO) mispricings. It is research and software infrastructure only.

**Not financial advice.** Nothing here is an offer, solicitation, or recommendation to trade. There is **no guaranteed PnL**. Markets can gap, quotes can go stale, and a half-filled arb is worse than no trade.

## Hard rules

- Default mode is paper (`ARB_MODE=paper`). Live trading is not enabled in this repo.
- Secrets never belong in this public repository. Copy `.env.example` to a local `.env` that stays gitignored.
- Official SDK only: [`polymarket-client`](https://pypi.org/project/polymarket-client/) (`from polymarket import AsyncPublicClient, AsyncSecureClient`). Do not use unofficial clients.
- Money uses `Decimal`. Do not put an LLM in the hot path.
- Do not create `ALLOW_LIVE`. Do not place live orders.

## Setup

Requires Python `>=3.11,<3.14`. Prefer [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
# Fill local secrets in .env only. Never commit .env, keys, or wallets.

uv sync
uv run pytest tests/test_money.py -q
```

`.env.example` documents the paper-mode keys. Leave `ARB_MODE=paper`. Relayer and wallet fields stay empty unless you are doing local paper work against your own account data.

## Layout

- `src/arb/money.py` — Decimal helpers (tick/size rounding down)
- `src/arb/config.py` — paper-default settings and the live gate
- `AGENTS.md` — shared law for Grok / Cursor
- `PLAN.md` — Task 1 done; remaining paper-only tasks

## License

MIT © 2026 Nikolai Kirkhaug / Cryptokid92
