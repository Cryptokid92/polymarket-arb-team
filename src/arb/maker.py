"""Maker completeness: rest bids so YES+NO still complete at min_edge.

Same trade as the taker hunt: own 1 YES + 1 NO for <= 1 - min_edge.
Makers pay 0. Does not loosen hunt. Does not take asks.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from arb.books import Book, Level, _reject_float
from arb.messages import GapFound

_ONE = Decimal("1")
_ZERO = Decimal("0")


@dataclass(frozen=True)
class MakerQuotes:
    yes_bid: Decimal
    no_bid: Decimal
    size: Decimal
    raw_edge: Decimal


def maker_complete_quotes(
    yes: Book,
    no: Book,
    *,
    min_edge: Decimal,
    max_gap: Decimal,
    min_size: Decimal,
    max_notional: Decimal,
    stale_ms: int,
    now_ms: int,
) -> MakerQuotes | None:
    """Join both best bids when their sum is a completeness edge.

    Size is the best-bid level we are willing to rest against, stepped
    to the min_order_size grid and clipped to max_notional. None when
    either book is thin, stale, or the bid sum is outside [min_edge, max_gap].
    """
    min_edge = _reject_float(min_edge, "min_edge")
    max_gap = _reject_float(max_gap, "max_gap")
    min_size = _reject_float(min_size, "min_size")
    max_notional = _reject_float(max_notional, "max_notional")
    if min_size <= _ZERO or max_notional <= _ZERO:
        return None
    if not yes.bids or not no.bids:
        return None
    older_ts = yes.ts_ms if yes.ts_ms < no.ts_ms else no.ts_ms
    if now_ms - older_ts > stale_ms:
        return None
    yes_bid = yes.bids[0].price
    no_bid = no.bids[0].price
    pair_px = yes_bid + no_bid
    if pair_px <= _ZERO:
        return None
    raw_edge = _ONE - pair_px
    if pair_px > _ONE - min_edge:
        return None
    if raw_edge > max_gap:
        return None
    cap = yes.bids[0].size
    if no.bids[0].size < cap:
        cap = no.bids[0].size
    notional_cap = max_notional / pair_px
    if notional_cap < cap:
        cap = notional_cap
    size = (cap / min_size).to_integral_value(rounding=ROUND_DOWN) * min_size
    if size < min_size:
        return None
    if size * pair_px > max_notional:
        return None
    return MakerQuotes(yes_bid=yes_bid, no_bid=no_bid, size=size, raw_edge=raw_edge)


def gap_from_maker_quotes(
    yes: Book,
    no: Book,
    quotes: MakerQuotes,
    now_ms: int,
    condition_id: str,
) -> GapFound:
    """Synthetic ask levels at the bid prices so risk.approve can re-walk."""
    older_ts = yes.ts_ms if yes.ts_ms < no.ts_ms else no.ts_ms
    return GapFound(
        condition_id=condition_id,
        yes_token_id=yes.token_id,
        no_token_id=no.token_id,
        yes_asks=[Level(price=quotes.yes_bid, size=quotes.size)],
        no_asks=[Level(price=quotes.no_bid, size=quotes.size)],
        fillable_shares=quotes.size,
        yes_vwap=quotes.yes_bid,
        no_vwap=quotes.no_bid,
        raw_edge=quotes.raw_edge,
        ts_ms=now_ms,
        book_age_ms=now_ms - older_ts,
    )
