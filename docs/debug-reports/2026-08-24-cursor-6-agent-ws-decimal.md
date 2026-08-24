# Cursor 6-lane debug — WS book Decimal ConversionSyntax

Date: 2026-08-24
Agent: `bc-5391436c-8966-43cd-a546-28e56fe94821`
Starting ref: `main` (`42e4384`)
Plan: [cursor-debug-ws-decimal-6-agents.md](../plans/cursor-debug-ws-decimal-6-agents.md)
PR: https://github.com/Cryptokid92/polymarket-arb-team/pull/15 (draft, not merged)

Paper only. No `ALLOW_LIVE`. No orders. Risk defaults unchanged.

## Root cause (proven)

Exact field: **`min_order_size`**.

Exact bad value after mapping: **`"None"`** (`str`).

On the wire / official SDK object: omitted or `""` → `MarketBookPayload.min_order_size is None`.

`polymarket-client` 0.6.0 `subscribe(MarketSpec(token_ids=...))` yields `MarketBookEvent` with `payload: MarketBookPayload`. On that payload, `min_order_size` and `tick_size` are `Decimal | None`. Streaming empty string is coerced to `None` (`_coerce_optional_decimalish`). REST `OrderBook.min_order_size` is a required `Decimal`, so the first list+books scan succeeded.

`orderbook_to_payload` did:

```python
min_size = getattr(book, "min_order_size", Decimal("5"))
...
"min_order_size": str(min_size),
```

The attribute exists and is `None`, so `getattr` does not use the default. `str(None)` is `"None"`. `book_from_payload` only defaults when the value is Python `None`, so `"None"` reaches `Book._decimal_fields` → `_reject_float` → `money.d("None")` → `decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>]`.

`tick_size=None` did not crash: `getattr(..., None) or getattr(..., Decimal("0.01"))` already fell through.

`last_trade_price` is not on this path. Bid/ask `price`/`size` are required decimals on official `OrderBookLevel` and were not the crash.

## Six lanes

1. **Payload hunter** — Official types: `MarketBookEvent` / `MarketBookPayload` (snapshot), `MarketPriceChangeEvent` / `PriceChange` (delta). Optional on WS: `min_order_size`, `tick_size`, `last_trade_price`, `hash`, `timestamp`. Levels require decimal strings.
2. **Mapper** — REST list hits `_apply_update` list branch with required decimals. WS `type=="book"` passes `.payload` into `orderbook_to_payload`. Asymmetry: `tick` has an `or` fallback; `min_order_size` does not.
3. **Book store** — `d("")` and `d("None")` raise `InvalidOperation` (ConversionSyntax in context). `d(None)` and floats raise `TypeError`. One bad snapshot does not write the store. `apply_price_change` can commit earlier changes then raise.
4. **Repro** — Official `parse_market_event` with `min_order_size=""` mapped to `min_order_size: "None"` and crashed the live path. REST-shaped dict missing the key already defaulted to `5` and did not crash.
5. **Runner policy** — Hour run must keep heartbeat, skip that update, log a reject. Do not trip the kill switch. Do not swallow all errors. Do not loosen `stale_ms` / `min_edge` / `max_gap`.
6. **Regression** — No existing test covered `str(None)`. Float refusal (`d()`, `Level`) must stay. Backtest/adversary still raise on empty/float prices (skip is paper ingest only).

## Paper-only patch (PR #15)

- Mapper never stringifies missing/empty tick or min size. `book_from_payload` keeps the previous REST values or defaults `0.01` / `5`.
- `consume()` logs `invalid_book_update` and continues on `InvalidOperation` only. Heartbeat is already marked. Last good book is kept.
- Floats still raise. Universe and risk filters unchanged.

## Test plan

- Official `parse_market_event` book with `min_order_size=""` applies; mapper never emits `"None"`.
- After REST `min_order_size=1`, WS omit keeps `1`.
- `run_paper` survives WS books without min size; kill switch stays off.
- One empty ask price is skipped (`invalid_book_update`); runner continues; last good book still hunts.
- Direct `apply_snapshot` still raises on float prices and empty prices.

`uv run pytest -q` — 127 passed on this branch (`313a7f6` plus this report).

## Not done

Do not merge to main unless Nikolai asks.
