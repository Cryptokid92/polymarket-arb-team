"""Hunt completeness gaps on ask depth. Never size from mids or bids."""

from __future__ import annotations

from decimal import Decimal

from arb.books import Book, _reject_float, fillable_pair_size, walk_asks
from arb.messages import GapFound

_ONE = Decimal("1")


def hunt(
    yes: Book,
    no: Book,
    min_edge: Decimal,
    min_size: Decimal,
    max_shares: Decimal,
    now_ms: int,
) -> GapFound | None:
    min_edge = _reject_float(min_edge, "min_edge")
    min_size = _reject_float(min_size, "min_size")
    max_shares = _reject_float(max_shares, "max_shares")

    fillable = fillable_pair_size(yes.asks, no.asks, min_size, max_shares)
    if fillable < min_size:
        return None

    yes_walk = walk_asks(yes.asks, fillable)
    no_walk = walk_asks(no.asks, fillable)
    if yes_walk is None or no_walk is None:
        return None

    yes_vwap, _filled_yes = yes_walk
    no_vwap, _filled_no = no_walk
    # Never round edge up.
    raw_edge = _ONE - yes_vwap - no_vwap
    if yes_vwap + no_vwap > _ONE - min_edge:
        return None

    older_ts = yes.ts_ms if yes.ts_ms < no.ts_ms else no.ts_ms
    return GapFound(
        condition_id=f"{yes.token_id}:{no.token_id}",
        yes_token_id=yes.token_id,
        no_token_id=no.token_id,
        yes_asks=list(yes.asks),
        no_asks=list(no.asks),
        fillable_shares=fillable,
        yes_vwap=yes_vwap,
        no_vwap=no_vwap,
        raw_edge=raw_edge,
        ts_ms=now_ms,
        book_age_ms=now_ms - older_ts,
    )
