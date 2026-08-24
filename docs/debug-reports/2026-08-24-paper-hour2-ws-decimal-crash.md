# Hour-2 crash — WS book Decimal ConversionSyntax

Date: 2026-08-24
Code: main `42e4384`
Data: `data/paper-hour2` (gitignored)

## What happened
1. REST list + books scan succeeded. Not halted.
2. `_updates` used `AsyncPublicClient.subscribe(MarketSpec(token_ids=...))`.
3. A WS book event hit `_apply_update` → `orderbook_to_payload` → `BookStore.apply_snapshot` → `book_from_payload` → pydantic `Book` → `_decimal_fields` → `money.d` → `decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>]`.
4. `scripts/paper_run.py` printed `paper_run: [<class 'decimal.ConversionSyntax'>]` and exited 1.
5. Kill switch did not trip. Dashboard process stayed up.

## Trace
- `src/arb/app.py` `consume()` → `_apply_update` (~351)
- `src/arb/books.py` `apply_snapshot` (~170), `book_from_payload` (~131), `_decimal_fields` (~49)
- `src/arb/money.py` `d` (~18)

REST snapshots parse. At least one WS field is not a Decimal-legal string (empty, null, or similar). Exact field not proven in this report. Six-agent Cursor debug is in flight.

## Effect
Hour runner cannot stay up. UI on `127.0.0.1:8765` shows the last scan. Repeated restarts appended more `neg_risk` rejects (78 × N).
