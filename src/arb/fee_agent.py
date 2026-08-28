"""Fee agent: price ask takes as FAK; rest bids as maker GTC. Rebates excluded."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from arb.books import _reject_float
from arb.fees import net_edge_maker, net_edge_taker, pair_taker_fees, taker_fee
from arb.messages import GapFound, Intent

# Explicit per-share taker buffer. Do not add other hardcoded bps.
_TAKER_BUFFER_PER_SHARE = Decimal("0.005")


class MarketFees(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    yes_rate: Decimal
    no_rate: Decimal

    @field_validator("yes_rate", "no_rate", mode="before")
    @classmethod
    def _decimal_only(cls, value: object) -> Decimal:
        return _reject_float(value, "fee_rate")


def _taker_ev(gap: GapFound, fees: MarketFees, size: Decimal) -> Decimal:
    pair_fees = pair_taker_fees(
        size,
        gap.yes_vwap,
        size,
        gap.no_vwap,
        fees.yes_rate,
        fees.no_rate,
    )
    return net_edge_taker(gap.raw_edge, size, pair_fees) - (_TAKER_BUFFER_PER_SHARE * size)


def choose_intent(
    gap: GapFound,
    fees: MarketFees,
    min_edge: Decimal,
    *,
    source: Literal["taker", "maker"] = "taker",
) -> Intent | None:
    """Ask-take (hunt) is taker_fak after fees+buffer, else None.
    Bid-rest (maker completeness) is maker_gtc when maker EV > 0.
    """
    min_edge = _reject_float(min_edge, "min_edge")
    if gap.raw_edge < min_edge:
        return None

    size = gap.fillable_shares
    maker_ev = net_edge_maker(gap.raw_edge, size)

    if source == "maker":
        if maker_ev > 0:
            return Intent(
                gap=gap,
                path="maker_gtc",
                size=size,
                yes_limit=gap.yes_vwap,
                no_limit=gap.no_vwap,
                expected_net_edge=maker_ev,
                taker_fee_yes=Decimal("0"),
                taker_fee_no=Decimal("0"),
            )
        return None
    taker_ev = _taker_ev(gap, fees, size)
    if taker_ev > 0:
        return Intent(
            gap=gap,
            path="taker_fak",
            size=size,
            yes_limit=gap.yes_vwap,
            no_limit=gap.no_vwap,
            expected_net_edge=taker_ev,
            taker_fee_yes=taker_fee(size, gap.yes_vwap, fees.yes_rate),
            taker_fee_no=taker_fee(size, gap.no_vwap, fees.no_rate),
        )
    return None
