"""Pure paper pipeline: hunt → risk → fee intent. No network."""

from __future__ import annotations

from decimal import Decimal

from arb.books import Book
from arb.config import Settings
from arb.executor import PaperBroker, PaperOrder
from arb.fee_agent import MarketFees, choose_intent
from arb.hunter import hunt
from arb.messages import Intent
from arb.risk import MarketFlags, Portfolio, approve


def run_pipeline(
    yes: Book,
    no: Book,
    settings: Settings,
    market_flags: MarketFlags,
    fees: MarketFees,
    portfolio: Portfolio,
    now_ms: int,
) -> Intent | None:
    min_size = (
        yes.min_order_size
        if yes.min_order_size >= no.min_order_size
        else no.min_order_size
    )
    gap = hunt(
        yes,
        no,
        settings.min_edge,
        min_size,
        Decimal("1000000"),
        now_ms,
    )
    if gap is None:
        return None
    approved = approve(gap, portfolio, settings, market_flags)
    if approved is None:
        return None
    return choose_intent(approved, fees, settings.min_edge)


async def paper_execute(
    intent: Intent, broker: PaperBroker
) -> tuple[PaperOrder, PaperOrder]:
    return await broker.post_pair(intent)
