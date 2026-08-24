"""Approve neg-risk full-set gaps. Clip to max notional. Decimal only."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from arb.config import Settings
from arb.money import round_size

try:
    from arb.fullset_hunt import FullSetGap
except ImportError:

    @dataclass(frozen=True)
    class FullSetGap:
        event_id: str
        token_ids: tuple[str, ...]
        fillable_shares: Decimal
        vwaps: tuple[Decimal, ...]
        raw_edge: Decimal
        ts_ms: int
        book_age_ms: int

_ZERO = Decimal("0")


def approve_full_set(
    gap: FullSetGap, settings: Settings, now_ms: int
) -> FullSetGap | None:
    """Return the gap (maybe size-clipped) or None."""
    _ = now_ms
    if gap.book_age_ms > settings.stale_ms:
        return None
    if gap.raw_edge > settings.max_gap:
        return None
    if gap.raw_edge < settings.min_edge:
        return None

    sum_v = sum(gap.vwaps, _ZERO)
    size = gap.fillable_shares
    if size * sum_v > settings.max_notional_per_trade:
        if sum_v <= _ZERO:
            return None
        size = round_size(settings.max_notional_per_trade / sum_v)
        if size <= _ZERO or size * sum_v > settings.max_notional_per_trade:
            return None
        return replace(gap, fillable_shares=size)
    return gap
