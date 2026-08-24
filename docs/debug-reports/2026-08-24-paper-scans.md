# Paper scans — 24 Aug 2026

Host: operator box (`/workspace/polymarket-arb-team`). Paper only. No `ALLOW_LIVE`. No orders.

Public geoblock on this host is blocked (US/AZ). Paper skips geoblock. Do not treat this host as a live venue.

## One-shot (earlier)
listed=20, universe=1, gaps=0, intents=0, rejects=`neg_risk` 19.

## Wider once
listed=80, universe=2, gaps=0, intents=0, rejects=`neg_risk` 78. Public API connected.

## Hour-1 (`data/paper-hour1`)
Same first-page shape. Halted after the first consider (see halt report). Runner died. UI at `127.0.0.1:8765`.

## Hour-2 (`data/paper-hour2`) after WS-age fix on main `42e4384`
First REST scan: listed=80, universe=2, gaps=0, intents=0, rejects=`neg_risk` 78. Not halted.

Five restarts stacked rejects to 390, all `neg_risk`. Runner then died on a WS book Decimal (see crash report). UI restarted on hour-2.
