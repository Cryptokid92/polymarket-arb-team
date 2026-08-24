"""Risk agent: refuse uncompletable, delayed, stale, and over-limit gaps."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from arb.books import walk_asks
from arb.config import Settings
from arb.messages import GapFound
from arb.money import round_size


@dataclass
class Portfolio:
    yes: dict[str, Decimal]  # condition_id -> shares
    no: dict[str, Decimal]
    open_pairs: int
    daily_pnl: Decimal
    halted: bool


class MarketFlags(BaseModel):
    accepting_orders: bool
    seconds_delay: int
    neg_risk: bool
    binary: bool


def _clip_to_notional(size: Decimal, pair_px: Decimal, max_notional: Decimal) -> Decimal:
    if pair_px <= 0:
        return Decimal("0")
    notional = size * pair_px
    if notional <= max_notional:
        return size
    return round_size(max_notional / pair_px)


def approve(
    gap: GapFound,
    portfolio: Portfolio,
    settings: Settings,
    market_flags: MarketFlags,
) -> GapFound | None:
    """Return the gap (maybe size-clipped) or None."""
    if portfolio.halted:
        return None
    if not market_flags.binary:
        return None
    if not market_flags.accepting_orders:
        return None
    if market_flags.seconds_delay > 0:
        return None
    if market_flags.neg_risk:
        return None
    if gap.book_age_ms > settings.stale_ms:
        return None
    if gap.raw_edge > settings.max_gap:
        return None
    if portfolio.open_pairs >= settings.max_open_pairs:
        return None
    if portfolio.daily_pnl <= -settings.max_daily_loss:
        return None

    pair_px = gap.yes_vwap + gap.no_vwap
    size = _clip_to_notional(gap.fillable_shares, pair_px, settings.max_notional_per_trade)
    if size <= 0:
        return None

    yes_walk = walk_asks(gap.yes_asks, size)
    no_walk = walk_asks(gap.no_asks, size)
    if yes_walk is None or no_walk is None:
        return None

    yes_vwap, _yes_filled = yes_walk
    no_vwap, _no_filled = no_walk
    walked_pair = yes_vwap + no_vwap
    if size * walked_pair > settings.max_notional_per_trade:
        size = _clip_to_notional(size, walked_pair, settings.max_notional_per_trade)
        if size <= 0:
            return None
        yes_walk = walk_asks(gap.yes_asks, size)
        no_walk = walk_asks(gap.no_asks, size)
        if yes_walk is None or no_walk is None:
            return None
        yes_vwap, _yes_filled = yes_walk
        no_vwap, _no_filled = no_walk
        if size * (yes_vwap + no_vwap) > settings.max_notional_per_trade:
            return None

    raw_edge = Decimal("1") - yes_vwap - no_vwap
    return gap.model_copy(
        update={
            "fillable_shares": size,
            "yes_vwap": yes_vwap,
            "no_vwap": no_vwap,
            "raw_edge": raw_edge,
        }
    )
