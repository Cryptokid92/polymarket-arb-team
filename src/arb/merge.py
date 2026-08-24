"""Merge complete YES/NO pairs. Paper pretends; live stays dark."""

from __future__ import annotations

from decimal import Decimal

from arb.books import _reject_float


def mergeable(yes_shares: Decimal, no_shares: Decimal) -> Decimal:
    yes_shares = _reject_float(yes_shares, "yes_shares")
    no_shares = _reject_float(no_shares, "no_shares")
    return yes_shares if yes_shares <= no_shares else no_shares


async def maybe_merge(
    client: object,
    condition_id: str,
    yes_shares: Decimal,
    no_shares: Decimal,
    mode: str,
) -> Decimal:
    qty = mergeable(yes_shares, no_shares)
    if qty <= 0:
        return Decimal("0")
    if mode != "live":
        return qty
    raise RuntimeError("live merge is Task 12")
