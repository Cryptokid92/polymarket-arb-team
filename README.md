# polymarket-arb-team

Paper-first completeness arbitrage bot for [Polymarket](https://polymarket.com).

This repository scaffolds a **paper-mode** specialist team that looks for completeness (YES + NO) mispricings. It is research and software infrastructure only. Paper bankroll is **$500** and is **not real money**.

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

# All open markets (walks list_markets pages; 5000-market windows).
# Still refuses neg-risk / delay / non-binary / short crypto windows.
# REST books in batches of 50 token ids (up to 4 in flight).
# Watches 100 pairs (200 tokens); remaining window pairs rotate every 1s.
# Next 5000 is listed, then the window swaps about every 60s.
# When the catalog cursor is exhausted, the next list is page 1 again.
# Do not subscribe all 1540. Do not raise 5000.
uv run python scripts/paper_run.py --all-markets --seconds 3600
# equivalent: --max-markets 0
# optional: --book-batch-size 50 --watch-pairs 100 --watch-rotate-s 1
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

`--record-books` writes watch-slice public books to `data/paper/books.jsonl` (gitignored) for `scripts/backtest_tape.py`. The dashboard shows closest walked edge / near-misses and paper alerts. Those are not live orders.

Standalone recorder (public client only):

```bash
uv run python scripts/record_books.py --all-markets --once --out data/paper/books.jsonl
uv run python scripts/backtest_tape.py --tape data/paper/books.jsonl
```

`backtest_tape.py` streams one market at a time so a 1GB hour tape does not have to sit in RAM. If the tape backtest verdict is `non_positive`, stop. Do not loosen risk. Do not go live.

Writes gitignored JSONL (covered by `data/`):

- `data/paper/gaps.jsonl` — hunter hits (edge, VWAPs, estimated maker/taker EV)
- `data/paper/intents.jsonl` — paper-only approved intents (`PaperBroker`)
- `data/paper/rejects.jsonl` — universe / risk / fee reject reasons
- `data/paper/stats.json` — markets listed / universe / unique listed / unique walked plus `bankroll`, `daily_pnl`, `fills`, and `heartbeat_ms` for the dashboard
- `data/paper/fills.jsonl` — paper fills and completeness PnL (not real money)

`paper_ui.py` shows paper bankroll, realized PnL (earned/lost), intents, fills, unique markets listed/walked across windows, the current list window, catalog wraps, and the watch slice. List window increments when the next 5000 is ready; if listing ate the 60s dwell it swaps without opening subscribe. If the JSONL files are missing it shows zeros and does not invent trades. Local Start/Stop pauses or launches `paper_run` (`ARB_MODE=paper`); Start is the human resume for a prior `ws_stale` when no `HALT` file is present. Start does not re-trip on stream age; a failed REST liveness probe still halts. The watch-rotate slider (1–120s) writes `control.json` and does not change risk caps. Data is GET; control POSTs are 127.0.0.1 only. Run status follows the newest JSONL timestamp, `stats.json` mtime, or `heartbeat_ms` — a live runner rewriting stats is **running**, not stale. Halt still comes only from `HALT` / sqlite. `ws_stale` means the stream or REST probe failed, not daily loss. Banner: **PAPER MODE. Not live. Not financial advice.** Auto-refreshes every 2s. Paper $500 is not real money.

`report_paper.py` prints: gaps seen, intents approved, estimated maker EV, estimated taker EV, reject reasons.

### Installed SDK notes (polymarket-client)

These match the installed client in this repo. If they drift, follow the installed signatures:

- `AsyncPublicClient.list_markets(closed=False, page_size=100)` — paginator; the runner walks pages (`async for page in pages`) for one 5000-market window. Resume later windows with official `page.next_cursor` / `from_cursor`. `--all-markets` / `--max-markets 0` means no user cap; the 5000 ceiling is the window size, not the whole catalog.
- `get_order_books(token_ids=...)` — snapshot asks+bids+depth, **batched** (default `--book-batch-size 50`). A failed batch is logged; other batches continue. One fat payload must not kill the run.
- `subscribe(MarketSpec(token_ids=...))` **is** present. The runner watches a first slice only (default `--watch-pairs 100` = 200 tokens) and rotates remaining universe pairs (`--watch-rotate-s 1`). If `subscribe` is missing on a future client, it polls `get_order_books` in the same batches.

## Layout

- `src/arb/money.py` — Decimal helpers (tick/size rounding down)
- `src/arb/config.py` — paper-default settings and the live gate
- `src/arb/app.py` — hunt → risk → fee pipeline and paper run loop
- `scripts/paper_run.py` — networked paper runner (public client only)
- `scripts/record_books.py` — record public YES/NO books for replay
- `scripts/backtest_tape.py` — replay a recorded tape (stop if EV is not positive)
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
