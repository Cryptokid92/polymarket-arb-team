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
uv run pytest -q
```

`.env.example` documents the paper-mode keys. Leave `ARB_MODE=paper`. Relayer and wallet fields stay empty unless you are doing local paper work against your own account data.

## Paper run (1 hour)

Paper only. Reads **public** books. **Cannot place orders.** Never constructs a secure trading client.

```bash
# Leave ARB_MODE=paper. Do not create ALLOW_LIVE.
uv run python scripts/paper_run.py --seconds 3600

# All open markets (walks list_markets pages; safety ceiling 5000).
# Still refuses neg-risk / delay / non-binary / short crypto windows.
# REST books in batches of 50 token ids. Watches 40 pairs (80 tokens);
# remaining universe pairs rotate every 90s. Do not subscribe all 1540.
uv run python scripts/paper_run.py --all-markets --seconds 3600
# equivalent: --max-markets 0
# optional: --book-batch-size 50 --watch-pairs 40 --watch-rotate-s 90
```

In another terminal, watch the gitignored logs (read-only local UI, binds `127.0.0.1:8765`):

```bash
uv run python scripts/paper_ui.py --data-dir data/paper
```

Then summarize from the command line if you want:

```bash
uv run python scripts/report_paper.py
```

`--place-orders` is rejected. If the public API is unreachable the runner exits with a clear error and does **not** fake gaps.

Writes gitignored JSONL (covered by `data/`):

- `data/paper/gaps.jsonl` — hunter hits (edge, VWAPs, estimated maker/taker EV)
- `data/paper/intents.jsonl` — paper-only approved intents (`PaperBroker`)
- `data/paper/rejects.jsonl` — universe / risk / fee reject reasons
- `data/paper/stats.json` — markets listed / universe / gap / intent / reject counts plus `heartbeat_ms` for the dashboard

`paper_ui.py` is read-only. If the JSONL files are missing it shows zeros and does not invent trades. Run status follows the newest JSONL timestamp, `stats.json` mtime, or `heartbeat_ms` — a live runner rewriting stats is **running**, not stale. Halt still comes only from `HALT` / sqlite. Banner: **PAPER MODE. Not live. Not financial advice.** Auto-refreshes every 2s.

`report_paper.py` prints: gaps seen, intents approved, estimated maker EV, estimated taker EV, reject reasons.

### Installed SDK notes (polymarket-client)

These match the installed client in this repo. If they drift, follow the installed signatures:

- `AsyncPublicClient.list_markets(closed=False, page_size=100)` — paginator; the runner walks pages (`async for page in pages`) until exhausted, `--max-markets`, or the 5000 safety ceiling. `--all-markets` / `--max-markets 0` means no user cap.
- `get_order_books(token_ids=...)` — snapshot asks+bids+depth, **batched** (default `--book-batch-size 50`). A failed batch is logged; other batches continue. One fat payload must not kill the run.
- `subscribe(MarketSpec(token_ids=...))` **is** present. The runner watches a first slice only (default `--watch-pairs 40` = 80 tokens) and rotates remaining universe pairs (`--watch-rotate-s 90`). If `subscribe` is missing on a future client, it polls `get_order_books` in the same batches.

## Layout

- `src/arb/money.py` — Decimal helpers (tick/size rounding down)
- `src/arb/config.py` — paper-default settings and the live gate
- `src/arb/app.py` — hunt → risk → fee pipeline and paper run loop
- `scripts/paper_run.py` — networked paper runner (public client only)
- `scripts/report_paper.py` — summarize a paper run
- `scripts/paper_ui.py` — read-only local dashboard (stdlib `http.server`)
- `AGENTS.md` — shared law for Grok / Cursor
- `PLAN.md` — Tasks 1–11 done; paper dashboard added; Task 12 stays dark

## License

MIT © 2026 Nikolai Kirkhaug / Cryptokid92

## Plans and debug reports

- [docs/guide/how-this-bot-works.md](docs/guide/how-this-bot-works.md) — how this completeness-arb bot works
- [docs/plans/](docs/plans/) — Grok Build and Cursor plans
- [docs/debug-reports/](docs/debug-reports/) — halt, crash, and review write-ups
