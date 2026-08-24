"""Detect naked leftover legs and plan a paper FAK flatten. No network."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from arb.books import _reject_float


class Hedge(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    side: Literal["YES", "NO"]
    action: Literal["SELL_FAK"]
    size: Decimal
    incident: bool = True

    @field_validator("size", mode="before")
    @classmethod
    def _decimal_only(cls, value: object) -> Decimal:
        return _reject_float(value, "hedge")


def naked_delta(yes_filled: Decimal, no_filled: Decimal) -> Decimal:
    yes_filled = _reject_float(yes_filled, "yes_filled")
    no_filled = _reject_float(no_filled, "no_filled")
    return yes_filled - no_filled


def hedge_plan(yes_filled: Decimal, no_filled: Decimal) -> Hedge | None:
    """If yes>no, sell excess YES FAK. If no>yes, sell excess NO FAK. v1 sells excess to flatten."""
    delta = naked_delta(yes_filled, no_filled)
    if delta > 0:
        return Hedge(side="YES", action="SELL_FAK", size=delta, incident=True)
    if delta < 0:
        return Hedge(side="NO", action="SELL_FAK", size=-delta, incident=True)
    return None


def after_timeout_hedge(
    yes_filled: Decimal,
    no_filled: Decimal,
    timed_out: bool,
) -> Hedge | None:
    """Paper hedge after timeout. Does not call the network."""
    if not timed_out:
        return None
    if naked_delta(yes_filled, no_filled) == 0:
        return None
    return hedge_plan(yes_filled, no_filled)
