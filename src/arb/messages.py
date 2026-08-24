"""Paper-mode bus messages. Level is reused from arb.books."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from arb.books import Level, _reject_float

__all__ = ["GapFound", "Intent", "Level"]


class GapFound(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    condition_id: str
    yes_token_id: str
    no_token_id: str
    yes_asks: list[Level]
    no_asks: list[Level]
    fillable_shares: Decimal
    yes_vwap: Decimal
    no_vwap: Decimal
    raw_edge: Decimal  # 1 - yes_vwap - no_vwap
    ts_ms: int
    book_age_ms: int

    @field_validator(
        "fillable_shares", "yes_vwap", "no_vwap", "raw_edge", mode="before"
    )
    @classmethod
    def _decimal_only(cls, value: object) -> Decimal:
        return _reject_float(value, "gap")


class Intent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    gap: GapFound
    path: Literal["maker_gtc", "taker_fak"]
    size: Decimal
    yes_limit: Decimal
    no_limit: Decimal
    expected_net_edge: Decimal
    taker_fee_yes: Decimal
    taker_fee_no: Decimal

    @field_validator(
        "size",
        "yes_limit",
        "no_limit",
        "expected_net_edge",
        "taker_fee_yes",
        "taker_fee_no",
        mode="before",
    )
    @classmethod
    def _decimal_only(cls, value: object) -> Decimal:
        return _reject_float(value, "intent")
