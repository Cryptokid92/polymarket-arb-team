# How this completeness-arb bot works

Paper-mode research code for [Polymarket](https://polymarket.com). It looks for the same-market case where YES and NO asks add to less than $1, then sizes a pair from walked ask depth.

It does not place live orders. It is not a trading product.

## What completeness arb is here

A binary market has two tokens: YES and NO. One share of each pays $1 at settlement (ignoring fees).

If you can buy both asks for less than $1, that difference is a completeness gap.

This bot:

- Stays inside one market. Same condition, YES token + NO token.
- Buys the ask on both sides. It does not size from mids, last trade, or top-of-book only.
- Reconstructs each book, then walks ask depth cheapest-first (VWAP).
- Size is the largest pair both books can fill, stepped down on the `min_order_size` grid (then clipped by risk notional).
- Emits a gap only when `yes_vwap + no_vwap <= 1 - min_edge` and fillable size is at least min size.
- Default `min_edge` is `0.01` (one cent per share). Default `max_gap` is `0.08`; larger than that is refused as too-good.

Raw edge is `1 - yes_vwap - no_vwap`. It is never rounded up. Money is `Decimal` everywhere. Floats are rejected.

This is not a directional bet. It is not cross-market arb. It is not a mid signal.

## What it is not

- Not live. `ARB_MODE` defaults to `paper`.
- Not financial advice. Nothing here is an offer, solicitation, or recommendation to trade.
- No guaranteed PnL. Quotes go stale. Depth disappears. A half-filled pair is worse than no trade.
- No LLM on the hot path: quotes, edge, sizing, orders, hedge, cancel.
- Official SDK only: [`polymarket-client`](https://pypi.org/project/polymarket-client/). Import path: `from polymarket import AsyncPublicClient, AsyncSecureClient`.
- The paper runner never constructs a secure trading client.
- Do not scrape influencer wallets.
- Do not create `ALLOW_LIVE`. Agents must not enable live.

## Pipeline

One Python process. Specialists are functions, not separate services. There is an in-process bus (`arb.bus`) if something wants to subscribe. The paper loop calls the pipeline directly.

1. **List markets.** `AsyncPublicClient.list_markets(closed=False, page_size=100)`. Walk official pages until the catalog ends, `--max-markets`, or the documented safety ceiling (`5000`). Default `--max-markets` is 20 (tests). `--all-markets` or `--max-markets 0` means no user cap. `markets_listed` is every market seen; `universe` is what `reject_universe` kept. If the public API is unreachable, the runner exits with a clear error and does not fake gaps.
2. **v1 universe filter.** Drop closed/archived, not accepting, neg-risk, delayed (`seconds_delay > 0`), missing YES/NO token ids, and 5/15-minute crypto windows (slug/question/tags matching crypto plus a 5 or 15 minute window).
3. **Books.** REST snapshot of kept YES/NO token ids in batches (`get_order_books`, default `--book-batch-size 50`). Apply each batch. A failed batch is logged (`book_batch_failed`) and skipped; `PublicApiError` only if every batch fails. Then websocket `subscribe(MarketSpec(token_ids=...))` on a first watch slice only (default `--watch-pairs 40` = 80 tokens). The slice **pins** up to 8 highest walked-edge pairs (`PIN_HOT_PAIRS`) and rotates the rest every `--watch-rotate-s` seconds (default 10). If `subscribe` is missing, poll REST in the same batches. `BookStore` applies snapshots and `price_change` deltas. Do not subscribe all ~1540 pairs at once. Do not raise the listing safety ceiling as a books-payload fix.
4. **Near-miss.** Every consider walks ask depth even when hunt is silent. Best walked `raw_edge`, fillable size, book age, and in-watch flag go to `stats.json` / `nearmiss.jsonl`. Thin books do not invent an edge from top-of-book. This is telemetry, not a trade.
5. **Hunt.** `hunt()` walks both ask books. No gap → nothing else runs. `min_edge` stays `0.01`.
6. **Risk.** `approve()` may clip size to `max_notional_per_trade` and re-walk both sides. Refusal reasons below.
7. **Fees / intent.** `choose_intent()` prefers maker GTC. Taker FAK only if EV is still positive after protocol fees plus a `0.005`/share buffer. A chosen intent also writes a local `alerts.jsonl` row (dashboard only; not an order).
8. **Paper executor.** `PaperBroker` writes a YES buy and a NO buy to JSONL with status `paper_posted`. No network. No CLOB order.
9. **Honest paper fill.** The networked runner does **not** assume both legs fill. Taker FAK may miss the second leg (`p_miss` default 0.3) and flatten leftover with a paper FAK sell (`incident=True`). Maker GTC rests until timeout, then fill, cancel, or hedge. Completeness settlement ($1/share) only when both legs fill. Cost above remaining bankroll is `insufficient_bankroll`. Live merge is Task 12.

`scripts/paper_run.py` is that loop. `--place-orders` is rejected. `--paper-bankroll` / `PAPER_BANKROLL` defaults to 500.

Merge and naked-leg hedge exist as paper helpers (`arb.merge`, `arb.naked_leg`): paper merge is `min(yes, no)` with no network; leftover size after timeout is a paper FAK sell (`incident=True`). The networked paper runner now paper-fills both legs and calls paper merge for completeness settlement. Live merge is Task 12.

## Fees

Protocol taker fee:

```
fee = C * feeRate * p * (1 - p)
```

`C` is shares. `p` is price. The result is quantized to `$0.01` with `ROUND_HALF_UP` (matches official 100-share USDC tables).

Makers pay 0. `maker_fee()` returns 0. Maker rebates are not added to EV.

Paper fee rates come from the listed market's `trading.fee_schedule.rate` when that value is a `Decimal`. Otherwise the mapper uses `0`. Same rate on YES and NO.

Fee agent, in order:

- Maker EV = `raw_edge * size`. If that is `> 0`, path is `maker_gtc` (taker fees recorded as 0).
- Else taker EV = `raw_edge * size - pair_taker_fees - 0.005 * size`. If that is `> 0`, path is `taker_fak`.
- Else no intent (`fee_ev_nonpositive`).

The `0.005`/share buffer is explicit. Do not add other hardcoded bps.

## Risk

Risk sees a hunter gap plus market flags plus a paper portfolio. It returns the gap (maybe smaller) or nothing.

It refuses:

| Check | What |
|---|---|
| Halt | `portfolio.halted` (kill switch already tripped, or `HALT` file) |
| Not binary | Market is not a YES/NO pair |
| Not accepting | `accepting_orders` is false |
| Delay | `seconds_delay > 0` |
| Neg-risk | Neg-risk market |
| Stale | Book age (`now - older of the two book timestamps`) `> stale_ms` (default 400) |
| Max gap | `raw_edge > max_gap` (default 0.08). Too-good. |
| Max pairs | `open_pairs >= max_open_pairs` (default 3) |
| Daily loss | `daily_pnl <= -max_daily_loss` (default 50) |
| Uncompletable | After notional clip, one or both ask walks fail |
| Over-notional | Clip to `max_notional_per_trade` (default 25) is zero, or the re-walk still exceeds the cap |

Named reject reasons in paper logs match those checks (`halted`, `not_binary`, `not_accepting`, `seconds_delay`, `neg_risk`, `stale`, `max_gap`, `max_open_pairs`, `daily_loss`). Walk/notional failure after those checks is logged as `risk_rejected`.

Universe rejects use the same words plus `closed` and `short_crypto_window`.

## Kill switch

`KillSwitch.evaluate()` trips and sets `halted=True` in sqlite. After halt, new intents are refused. It does not auto-resume. `resume()` is human-only and refuses if a `HALT` file is still present.

It trips on:

1. **Daily loss.** Realized PnL plus optional unrealized `<= -max_daily_loss`.
2. **`HALT` file** in the project root.
3. **WS silence.** Age of last stream/poll *receive* `> ws_stale_ms` (default 3000). This is `StreamHeartbeat` in `app.py`: time of the last REST snapshot or WS/poll delivery. It is **not** CLOB `Book.ts_ms`. Book timestamps are only for hunter/risk `stale_ms`.
4. **Hedge incidents.** `>= 3` rows in sqlite `hedge_incidents` in the last hour.

Paper halt only sets the flag. Live `cancel_all` is Task 12.

The paper runner wires halt-file and WS-silence into this loop. It restores `daily_pnl` / paper bankroll from sqlite (default bankroll 500) and updates them on paper fills. It does not write hedge incidents on a complete pair fill.

## Paper logs and UI

Leave `ARB_MODE=paper`. Do not create `ALLOW_LIVE`.

```bash
# Public books only. Cannot place orders.
uv run python scripts/paper_run.py --seconds 3600

# All open markets (page walk; safety ceiling 5000). Subscribe only v1 pairs.
uv run python scripts/paper_run.py --all-markets --seconds 3600
```

In another terminal:

```bash
uv run python scripts/paper_ui.py --data-dir data/paper
```

Then:

```bash
uv run python scripts/report_paper.py
```

`--once` is one list+book cycle, then exit. `--place-orders` is rejected on both runner and UI. `--all-markets` walks listing pages (ceiling 5000). `--book-batch-size`, `--watch-pairs`, and `--watch-rotate-s` cap REST/WS payloads; they do not loosen universe or risk.

Logs are gitignored under `data/` (default `data/paper/`):

- `gaps.jsonl` — hunter hits (edge, VWAPs, estimated maker/taker EV, optional reject reason)
- `intents.jsonl` — paper-only approved intents (`PaperBroker`)
- `rejects.jsonl` — universe / risk / fee reasons
- `nearmiss.jsonl` — closest walked books (new best or non-negative walked edge)
- `alerts.jsonl` — local paper alerts when an intent is chosen
- `books.jsonl` — optional recorded public books (`--record-books`)
- `stats.json` — listed / universe / gap / intent / reject / fill counts, `bankroll`, `daily_pnl`, closest edge, histogram, `heartbeat_ms`
- `fills.jsonl` — paper fills, completed pairs, naked incidents
- `control.json` — local pause + watch-rotate interval (10–120s)
- `state.sqlite` — halt flag, halt reason, paper fills, bankroll, daily_pnl (path injectable)

`paper_ui.py` is stdlib `http.server`. Binds `127.0.0.1:8765`. Banner: **PAPER MODE. Not live. Not financial advice.** Auto-refresh every 2s. Shows paper bankroll, earned/lost, intents, fills. Local Start/Stop and the watch-rotate slider are POSTs to `/api/control` only. Missing logs show zeros. It does not invent trades. Hosts other than localhost are refused. Paper $500 is not real money.

`report_paper.py` prints gaps seen, intents approved, estimated maker EV, estimated taker EV, reject reasons, and halt reason if sqlite has one.

## Live gate (document only)

Live is allowed only when **both** are true:

1. `ARB_MODE=live`
2. A **human-created** `ALLOW_LIVE` file in the project root whose first line is today's ISO date (`YYYY-MM-DD`)

`LiveBroker` raises without that gate. With the gate it still raises: live SDK calls are not implemented. Task 12 (live path) is not built. Do not enable live. Do not create `ALLOW_LIVE`. Cursor reviews must not flip the gate.

Paper preflight skips secrets and geoblock. Live preflight would check the date file, keys, caps, and an injected geoblock fetcher. Default tests stay offline.

## Known paper-run issues

From `docs/debug-reports/`. Be precise: these happened on the operator box.

### Hour-1 halt — book age used as WS age

First hour run halted with `meta.halted=1`, no `HALT` file, empty fills, `daily_pnl` unset. All rejects were `neg_risk`.

Cause: `consider()` passed book quote age (`now - min(yes.ts_ms, no.ts_ms)`) into `KillSwitch.evaluate` as `ws_age_ms`. CLOB REST book timestamps are often older than 3s. First consider on the universe markets tripped `ws_stale` permanently (no auto-resume). Book staleness already had `stale_ms=400`. Risk was not loosened. Early `trip()` did not store a reason.

Fix: `StreamHeartbeat` (last stream/poll receive). Merged to main as `42e4384`. See [hour-1 halt](../debug-reports/2026-08-24-paper-hour1-halt.md) and the [WS-age review](../debug-reports/2026-08-24-cursor-review-ws-age.md).

### Hour-2 crash — WS book Decimal, `min_order_size` None

After the WS-age fix, the first REST scan worked (listed=80, universe=2, gaps=0, all rejects `neg_risk`). Not halted. Then `subscribe(MarketSpec)` delivered a book event. `orderbook_to_payload` → `BookStore.apply_snapshot` → `money.d` raised `decimal.InvalidOperation: ConversionSyntax`. `paper_run` printed that and exited 1. Kill switch did not trip. UI stayed up.

The crash report did not dump the raw WS payload. The mapper does `str(getattr(book, "min_order_size", Decimal("5")))`. If the WS object has the attribute set to `None`, that becomes the string `"None"`, which `Decimal` cannot parse. Tick uses `or` and falls through; min size does not. REST snapshots parse.

Six-agent Cursor debug was still in flight when that report was filed. Hour runner cannot stay up after subscribe starts. Restarts stacked more `neg_risk` rejects. See [hour-2 crash](../debug-reports/2026-08-24-paper-hour2-ws-decimal-crash.md).

### Scans

Public API connected. `--max-markets 80` was one page, mostly `neg_risk`, so `listed=80` / `universe=1–2` was not the full catalog. `--all-markets` walks pages (ceiling 5000) and still filters the v1 universe. Hour-6 then died on one `get_order_books` of ~3080 token ids (`Payload exceeds the limit`). Books are now batched (50 ids); the hour watch is a 40-pair slice that rotates. No gaps in those early runs. This host is geoblocked for live (US/AZ). Paper skips geoblock. Do not treat this host as a live venue.

### Hour-6 crash — fat `get_order_books` payload

`--all-markets` listed 5000 / universe 1540 / 3460 rejects (3352 `neg_risk`). Then one REST books call for every universe token id failed: `public API is unreachable: Payload exceeds the limit`. Process exited. No hour watch. Listing pagination was fine; do not raise `LIST_SAFETY_CAP`. See [hour-6 payload](../debug-reports/2026-08-24-hour6-payload-limit.md).

## Where the code lives

| Piece | Path |
|---|---|
| Shared law | `AGENTS.md` |
| Task list | `PLAN.md` |
| Paper-default settings + live gate | `src/arb/config.py` |
| Paper loop + universe + heartbeat | `src/arb/app.py` |
| Near-miss / closest book | `src/arb/nearmiss.py` |
| Hot watch pin + rotate | `src/arb/watch.py` |
| Local paper alerts | `src/arb/alerts.py` |
| Ask walk / book store | `src/arb/books.py` |
| Hunter | `src/arb/hunter.py` |
| Risk | `src/arb/risk.py` |
| Taker fee math | `src/arb/fees.py` |
| Maker vs taker intent | `src/arb/fee_agent.py` |
| Paper JSONL broker; live stub | `src/arb/executor.py` |
| Kill switch | `src/arb/killswitch.py` |
| Sqlite state | `src/arb/state.py` |
| Networked paper runner | `scripts/paper_run.py` |
| Public book recorder | `scripts/record_books.py` |
| Tape backtest | `scripts/backtest_tape.py` |
| Read-only UI | `scripts/paper_ui.py` |
| CLI summary | `scripts/report_paper.py` |
