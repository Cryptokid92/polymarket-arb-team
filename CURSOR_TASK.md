# Cursor review — list all open markets (not Task 12)

Review the paper catalog walk. Do **not** implement Task 12. Do **not** create `ALLOW_LIVE`.

## Run

```bash
uv run pytest -q
```

## Do not

- Do not enable live trading.
- Do not create `ALLOW_LIVE`.
- Do not place live orders.
- Do not construct `AsyncSecureClient`.
- Do not call the live network in default tests.
- Do not put an LLM in the hot path.
- Do not commit secrets, `.env`, keys, paper fills, `data/`, sqlite, or paper JSONL with account data.
- Do not loosen universe or risk: still refuse neg-risk, delay, non-binary, short crypto windows, `stale_ms`, `min_edge`, `max_gap`.

## Check — list walk

- `_iter_listed_markets` walks official pages (`async for page in listed` / `page.items`). It does **not** call `list_markets(page_size=max_markets)`.
- `LIST_PAGE_SIZE = 100`. `LIST_SAFETY_CAP = 5000` is documented.
- `--max-markets 0` and `--all-markets` mean no user cap (safety ceiling still applies). Default `--max-markets` stays 20.
- `markets_listed` = all seen. `universe` = kept after `reject_universe`.
- Subscribe / `get_order_books` only the kept v1 YES/NO token pairs. No neg-risk books.
- README and `docs/guide/how-this-bot-works.md` mention `--all-markets`.

## Check — live gate

- `live_allowed()` is still false without a human `ALLOW_LIVE` dated today, and false when `ARB_MODE=paper`.
- Paper runner cannot place live orders.
- No `ALLOW_LIVE` file in the repo.

## Check — docs

- `docs/plans/cursor-list-all-markets.md` plus the short debug note.
- `docs/plans/README.md` lists both.
