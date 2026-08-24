"""Paper bankroll, pair fills, and completeness settlement. No live client."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from arb.fee_agent import MarketFees
from arb.fees import maker_fee, net_edge_maker, net_edge_taker, pair_taker_fees
from arb.merge import maybe_merge
from arb.messages import Intent
from arb.money import d
from arb.state import StateStore

_ONE = Decimal("1")
_ZERO = Decimal("0")


def _require_decimal(value: Decimal, name: str) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError(f"{name} must be Decimal, not {type(value).__name__}")
    return value


def pair_fees_for_intent(intent: Intent, fees: MarketFees) -> Decimal:
    """Makers pay 0. Taker FAK uses protocol pair_taker_fees. No rebate."""
    if intent.path == "maker_gtc":
        return maker_fee(
            intent.size, intent.gap.yes_vwap, fees.yes_rate
        ) + maker_fee(intent.size, intent.gap.no_vwap, fees.no_rate)
    return pair_taker_fees(
        intent.size,
        intent.gap.yes_vwap,
        intent.size,
        intent.gap.no_vwap,
        fees.yes_rate,
        fees.no_rate,
    )


def pair_cost(intent: Intent, fees: MarketFees) -> Decimal:
    """Cash to buy both legs at gap VWAPs plus pair fees."""
    notional = intent.size * (intent.gap.yes_vwap + intent.gap.no_vwap)
    return notional + pair_fees_for_intent(intent, fees)


def completeness_pnl(intent: Intent, fees: MarketFees) -> Decimal:
    """Completed pair is worth $1/share.

    Total PnL = size * (1 - yes_vwap - no_vwap) - pair_fees.
    Makers: pair_fees is 0. Rebates are never added.
    """
    pair_fees = pair_fees_for_intent(intent, fees)
    raw = _ONE - intent.gap.yes_vwap - intent.gap.no_vwap
    if intent.path == "maker_gtc":
        return net_edge_maker(raw, intent.size)
    return net_edge_taker(raw, intent.size, pair_fees)


@dataclass
class PaperFillResult:
    accepted: bool
    reject_reason: str | None
    size: Decimal
    yes_vwap: Decimal
    no_vwap: Decimal
    pair_fees: Decimal
    cost: Decimal
    pnl: Decimal
    bankroll: Decimal
    daily_pnl: Decimal
    path: str
    condition_id: str


class PaperLedger:
    """Paper-only fills against sqlite. Never constructs a trading client."""

    def __init__(
        self,
        store: StateStore,
        *,
        bankroll: Decimal,
        daily_pnl: Decimal,
    ) -> None:
        self.store = store
        self.bankroll = _require_decimal(d(bankroll), "bankroll")
        self.daily_pnl = _require_decimal(d(daily_pnl), "daily_pnl")

    async def try_fill(
        self,
        intent: Intent,
        fees: MarketFees,
        now_ms: int,
        *,
        mode: str = "paper",
    ) -> PaperFillResult:
        if mode == "live":
            raise RuntimeError("paper ledger will not fill live")
        cost = pair_cost(intent, fees)
        pair_fees = pair_fees_for_intent(intent, fees)
        if cost > self.bankroll:
            return PaperFillResult(
                accepted=False,
                reject_reason="insufficient_bankroll",
                size=intent.size,
                yes_vwap=intent.gap.yes_vwap,
                no_vwap=intent.gap.no_vwap,
                pair_fees=pair_fees,
                cost=cost,
                pnl=_ZERO,
                bankroll=self.bankroll,
                daily_pnl=self.daily_pnl,
                path=intent.path,
                condition_id=intent.gap.condition_id,
            )

        yes_cid = f"paper-yes-{uuid.uuid4()}"
        no_cid = f"paper-no-{uuid.uuid4()}"
        condition_id = intent.gap.condition_id
        self.store.record_fill(
            yes_cid, condition_id, intent.size, intent.gap.yes_vwap, now_ms
        )
        self.store.record_fill(
            no_cid, condition_id, intent.size, intent.gap.no_vwap, now_ms
        )
        self.store.set_inventory(condition_id, intent.size, intent.size)
        qty = await maybe_merge(
            object(), condition_id, intent.size, intent.size, mode
        )
        leftover_yes = intent.size - qty
        leftover_no = intent.size - qty
        self.store.set_inventory(condition_id, leftover_yes, leftover_no)
        pnl = completeness_pnl(intent, fees)
        self.bankroll = self.bankroll + pnl
        self.daily_pnl = self.daily_pnl + pnl
        self.store.set_bankroll(self.bankroll)
        self.store.set_daily_pnl(self.daily_pnl)
        return PaperFillResult(
            accepted=True,
            reject_reason=None,
            size=intent.size,
            yes_vwap=intent.gap.yes_vwap,
            no_vwap=intent.gap.no_vwap,
            pair_fees=pair_fees,
            cost=cost,
            pnl=pnl,
            bankroll=self.bankroll,
            daily_pnl=self.daily_pnl,
            path=intent.path,
            condition_id=condition_id,
        )

    async def settle_full_set(
        self,
        token_vwaps: Sequence[Decimal],
        size: Decimal,
        now_ms: int,
        *,
        event_id: str = "",
        mode: str = "paper",
    ) -> PaperFillResult:
        if mode == "live":
            raise RuntimeError("paper ledger will not fill live")
        size = _require_decimal(d(size), "size")
        vwaps = tuple(_require_decimal(d(v), "token_vwaps") for v in token_vwaps)
        sum_v = sum(vwaps, _ZERO)
        cost = size * sum_v
        yes_vwap = vwaps[0] if vwaps else _ZERO
        no_vwap = vwaps[1] if len(vwaps) > 1 else _ZERO
        if cost > self.bankroll:
            return PaperFillResult(
                accepted=False,
                reject_reason="insufficient_bankroll",
                size=size,
                yes_vwap=yes_vwap,
                no_vwap=no_vwap,
                pair_fees=_ZERO,
                cost=cost,
                pnl=_ZERO,
                bankroll=self.bankroll,
                daily_pnl=self.daily_pnl,
                path="fullset_taker",
                condition_id=event_id,
            )

        for i, vwap in enumerate(vwaps):
            cid = f"paper-fullset-{i}-{uuid.uuid4()}"
            self.store.record_fill(cid, event_id, size, vwap, now_ms)
        pnl = size * (_ONE - sum_v)
        self.bankroll = self.bankroll + pnl
        self.daily_pnl = self.daily_pnl + pnl
        self.store.set_bankroll(self.bankroll)
        self.store.set_daily_pnl(self.daily_pnl)
        return PaperFillResult(
            accepted=True,
            reject_reason=None,
            size=size,
            yes_vwap=yes_vwap,
            no_vwap=no_vwap,
            pair_fees=_ZERO,
            cost=cost,
            pnl=pnl,
            bankroll=self.bankroll,
            daily_pnl=self.daily_pnl,
            path="fullset_taker",
            condition_id=event_id,
        )
