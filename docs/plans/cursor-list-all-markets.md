# Cursor plan — list all open markets (paper)

Date: 2026-08-24
Agent: Grok implementer
Starting ref: `main` (`2a044d0`) after PR #19

Paper only. Never create `ALLOW_LIVE`. Never place orders. Do not loosen hunter `stale_ms`, `min_edge`, `max_gap`, universe filters (neg-risk, delay, non-binary, short crypto windows), or kill rules.

## Ask

Nikolai wants every open Polymarket market listed, not `--max-markets 80`. Hour scans showed `listed=80` / `universe=2` / 78 `neg_risk` because `_iter_listed_markets` requested **one page** with `page_size=max_markets` and stopped.

## Design

- Official SDK paginator: `list_markets(closed=False, page_size=LIST_PAGE_SIZE)` then `async for page in pages` / `page.items`.
- `LIST_PAGE_SIZE = 100`. Never pass `max_markets` as `page_size`.
- Walk pages until exhausted, the user cap, or `LIST_SAFETY_CAP = 5000`.
- `--max-markets 0` or `--all-markets` means no user cap (safety ceiling still applies). Default stays 20 for tests.
- Apply `reject_universe` to **each** listed market.
- Subscribe / poll **only** the kept v1 YES/NO token pairs. Do not subscribe to hundreds of neg-risk books.
- Stats: `markets_listed` = all seen, `universe` = kept, reject reasons unchanged.

## Tests

TDD in `tests/test_paper_run.py`. `uv run pytest -q` green. Official SDK only. Offline mocks.

## Git

Branch + PR. Do not merge to main.
