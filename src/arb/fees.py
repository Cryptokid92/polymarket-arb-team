"""Protocol taker-fee math. Makers pay 0. Rebates are never part of EV."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_ONE = Decimal("1")
# Official 100-share tables are published in USDC to 2 decimals (e.g. $0.07).
_TABLE_TICK = Decimal("0.01")


def _require_decimal(value: Decimal, name: str) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError(f"{name} must be Decimal, not {type(value).__name__}")
    return value


def taker_fee(shares: Decimal, price: Decimal, fee_rate: Decimal) -> Decimal:
    """fee = C * feeRate * p * (1-p). Makers return 0."""
    shares = _require_decimal(shares, "shares")
    price = _require_decimal(price, "price")
    fee_rate = _require_decimal(fee_rate, "fee_rate")
    raw = shares * fee_rate * price * (_ONE - price)
    return raw.quantize(_TABLE_TICK, rounding=ROUND_HALF_UP)


def pair_taker_fees(
    yes_shares: Decimal,
    yes_price: Decimal,
    no_shares: Decimal,
    no_price: Decimal,
    fee_rate_yes: Decimal,
    fee_rate_no: Decimal,
) -> Decimal:
    return taker_fee(yes_shares, yes_price, fee_rate_yes) + taker_fee(
        no_shares, no_price, fee_rate_no
    )


def net_edge_taker(raw_edge: Decimal, shares: Decimal, fees: Decimal) -> Decimal:
    """(raw_edge * shares) - fees"""
    raw_edge = _require_decimal(raw_edge, "raw_edge")
    shares = _require_decimal(shares, "shares")
    fees = _require_decimal(fees, "fees")
    return (raw_edge * shares) - fees


def net_edge_maker(raw_edge: Decimal, shares: Decimal) -> Decimal:
    """raw_edge * shares  # maker fee is 0; do not add rebate"""
    raw_edge = _require_decimal(raw_edge, "raw_edge")
    shares = _require_decimal(shares, "shares")
    return raw_edge * shares


def maker_fee(shares: Decimal, price: Decimal, fee_rate: Decimal) -> Decimal:
    """Makers pay 0. Do not credit a rebate."""
    _require_decimal(shares, "shares")
    _require_decimal(price, "price")
    _require_decimal(fee_rate, "fee_rate")
    return Decimal("0")
