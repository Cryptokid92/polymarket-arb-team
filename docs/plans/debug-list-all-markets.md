# Debug note — `--max-markets 80` was one page

Date: 2026-08-24
Paper only. No `ALLOW_LIVE`.

Hour-2 / hour-5 scans on main: `listed=80`, `universe=1–2`, almost every reject `neg_risk`. That was not “all open markets.” `_iter_listed_markets` called `list_markets(page_size=max_markets)` and stopped after `len(items) >= max_markets`, so 80 was a single catalog page (Gamma’s first page is mostly neg-risk).

`--max-markets 0` was also wrong: `len(items) >= 0` is true after the first append, so a zero cap listed one market.

Fix: walk official pages at `page_size=100` until the catalog ends or the 5000 safety ceiling. Filter with `reject_universe`. Subscribe only the kept pairs. Caps (`stale_ms`, `min_edge`, `max_gap`) stay put.

See [cursor-list-all-markets.md](cursor-list-all-markets.md).
