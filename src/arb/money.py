"""Decimal-only money helpers. Public APIs never take or emit float."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

D = Decimal

_SIZE_TICK = Decimal("0.01")


def d(x: str | int | Decimal) -> Decimal:
    if type(x) is Decimal:
        return x
    if type(x) is int:
        return Decimal(x)
    if type(x) is str:
        return Decimal(x)
    raise TypeError(f"d() accepts str | int | Decimal, not {type(x).__name__}")


def round_price(price: Decimal, tick: Decimal) -> Decimal:
    """Round a buy price down to the nearest tick."""
    if type(price) is not Decimal or type(tick) is not Decimal:
        raise TypeError("round_price() requires Decimal price and tick")
    if tick <= 0:
        raise ValueError("tick must be positive")
    ticks = (price / tick).to_integral_value(rounding=ROUND_DOWN)
    return ticks * tick


def round_size(size: Decimal) -> Decimal:
    """Round size down to 0.01."""
    if type(size) is not Decimal:
        raise TypeError("round_size() requires Decimal size")
    return size.quantize(_SIZE_TICK, rounding=ROUND_DOWN)
