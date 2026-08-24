# Cursor plan — debug WS book Decimal crash (6 sub-agents)

Date: 2026-08-24
Agent: `bc-5391436c-8966-43cd-a546-28e56fe94821`
Starting ref: `main` (`42e4384`)

Paper only. Never create `ALLOW_LIVE`. Never place orders. Do not loosen risk. Do not merge unless asked.

## Symptom
First REST scan works. Then `subscribe(MarketSpec)` delivers a book event. `apply_snapshot` → `money.d` → `decimal.InvalidOperation: ConversionSyntax`. `paper_run` prints that and exits 1. Kill switch is not tripped.

## Six parallel lanes
1. Payload hunter — official `polymarket-client` 0.6.0 subscribe event shape.
2. Mapper — `orderbook_to_payload` / `_apply_update` WS vs REST.
3. Book store — `books.py` / `money.d` / why REST works and WS dies.
4. Repro — failing unit test with a realistic bad payload.
5. Runner policy — bad tick must not kill the hour; do not swallow all errors.
6. Regression — float refusal and adversary tests stay.

## After
Debug report: [2026-08-24-cursor-6-agent-ws-decimal.md](../debug-reports/2026-08-24-cursor-6-agent-ws-decimal.md). Field proven (`min_order_size` → `"None"`). Paper-only patch on PR #15. Do not merge unless asked.
