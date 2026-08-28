"""Paper bankroll, pair fills, and completeness settlement. No live client."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from arb.backtest import _MissRng, _maker_side_fills, _maker_side_taken, walk_bids
from arb.books import Book, BookStore
from arb.fee_agent import MarketFees
from arb.fees import maker_fee, net_edge_maker, net_edge_taker, pair_taker_fees, taker_fee
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
    outcome: str = "filled"
    naked: bool = False
    hedge_pnl: Decimal = Decimal("0")
    completed: bool = True


@dataclass
class RestingPair:
    intent: Intent
    fees: MarketFees
    posted_yes: Book
    posted_no: Book
    posted_ms: int


class PaperLedger:
    """Paper-only fills against sqlite. Never constructs a trading client."""

    def __init__(
        self,
        store: StateStore,
        *,
        bankroll: Decimal,
        daily_pnl: Decimal,
        honest: bool = False,
        p_miss: Decimal = Decimal("0.3"),
        rng_seed: int = 0,
        hedge_slippage: Decimal = Decimal("0.01"),
        maker_rest_ms: int = 400,
    ) -> None:
        self.store = store
        self.bankroll = _require_decimal(d(bankroll), "bankroll")
        self.daily_pnl = _require_decimal(d(daily_pnl), "daily_pnl")
        self.honest = honest
        self.p_miss = _require_decimal(d(p_miss), "p_miss")
        self.hedge_slippage = _require_decimal(d(hedge_slippage), "hedge_slippage")
        self.maker_rest_ms = int(maker_rest_ms)
        self._rng = _MissRng(int(rng_seed))
        self._rests: list[RestingPair] = []

    def has_rest(self, condition_id: str) -> bool:
        return any(rest.intent.gap.condition_id == condition_id for rest in self._rests)

    @property
    def resting_pairs(self) -> int:
        return len(self._rests)

    def _rejected(
        self,
        intent: Intent,
        fees: MarketFees,
        reason: str,
    ) -> PaperFillResult:
        pair_fees = pair_fees_for_intent(intent, fees)
        cost = pair_cost(intent, fees)
        return PaperFillResult(
            accepted=False,
            reject_reason=reason,
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
            outcome="rejected",
            naked=False,
            hedge_pnl=_ZERO,
            completed=False,
        )

    async def _complete_pair(
        self,
        intent: Intent,
        fees: MarketFees,
        now_ms: int,
        *,
        mode: str,
    ) -> PaperFillResult:
        pair_fees = pair_fees_for_intent(intent, fees)
        cost = pair_cost(intent, fees)
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
            outcome="filled",
            naked=False,
            hedge_pnl=_ZERO,
            completed=True,
        )

    def _hedge_sell_px(
        self, book: Book | None, size: Decimal, fallback: Decimal
    ) -> Decimal:
        if book is not None:
            walked = walk_bids(book.bids, size)
            if walked is not None:
                bid_vwap = walked[0]
            elif book.bids:
                bid_vwap = book.bids[0].price
            else:
                bid_vwap = _ZERO
        else:
            bid_vwap = fallback
        px = bid_vwap - self.hedge_slippage
        if px < _ZERO:
            return _ZERO
        return px

    def _naked_leg(
        self,
        intent: Intent,
        fees: MarketFees,
        now_ms: int,
        *,
        filled_side: str,
        book: Book | None,
    ) -> PaperFillResult:
        size = intent.size
        if filled_side == "YES":
            buy_px = intent.gap.yes_vwap
            fee = (
                taker_fee(size, buy_px, fees.yes_rate)
                if intent.path == "taker_fak"
                else _ZERO
            )
        else:
            buy_px = intent.gap.no_vwap
            fee = (
                taker_fee(size, buy_px, fees.no_rate)
                if intent.path == "taker_fak"
                else _ZERO
            )
        sell_px = self._hedge_sell_px(book, size, buy_px)
        cost = size * buy_px + fee
        proceeds = size * sell_px
        pnl = proceeds - cost
        condition_id = intent.gap.condition_id
        self.store.record_fill(
            f"paper-{filled_side.lower()}-{uuid.uuid4()}",
            condition_id,
            size,
            buy_px,
            now_ms,
        )
        self.store.record_fill(
            f"paper-hedge-{uuid.uuid4()}",
            condition_id,
            size,
            sell_px,
            now_ms,
        )
        self.store.record_hedge_incident(now_ms)
        self.store.set_inventory(condition_id, _ZERO, _ZERO)
        self.bankroll = self.bankroll + pnl
        self.daily_pnl = self.daily_pnl + pnl
        self.store.set_bankroll(self.bankroll)
        self.store.set_daily_pnl(self.daily_pnl)
        return PaperFillResult(
            accepted=True,
            reject_reason=None,
            size=size,
            yes_vwap=intent.gap.yes_vwap,
            no_vwap=intent.gap.no_vwap,
            pair_fees=fee,
            cost=cost,
            pnl=pnl,
            bankroll=self.bankroll,
            daily_pnl=self.daily_pnl,
            path=intent.path,
            condition_id=condition_id,
            outcome="naked",
            naked=True,
            hedge_pnl=pnl,
            completed=False,
        )

    async def try_fill(
        self,
        intent: Intent,
        fees: MarketFees,
        now_ms: int,
        *,
        mode: str = "paper",
        yes: Book | None = None,
        no: Book | None = None,
    ) -> PaperFillResult:
        if mode == "live":
            raise RuntimeError("paper ledger will not fill live")
        cost = pair_cost(intent, fees)
        if cost > self.bankroll:
            return self._rejected(intent, fees, "insufficient_bankroll")

        if not self.honest:
            return await self._complete_pair(intent, fees, now_ms, mode=mode)

        if intent.path == "maker_gtc":
            if yes is None or no is None:
                return await self._complete_pair(intent, fees, now_ms, mode=mode)
            self._rests.append(
                RestingPair(
                    intent=intent,
                    fees=fees,
                    posted_yes=yes,
                    posted_no=no,
                    posted_ms=now_ms,
                )
            )
            pair_fees = pair_fees_for_intent(intent, fees)
            return PaperFillResult(
                accepted=True,
                reject_reason=None,
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
                outcome="resting",
                naked=False,
                hedge_pnl=_ZERO,
                completed=False,
            )

        miss_second = self._rng.second_fak_misses(self.p_miss)
        if not miss_second:
            return await self._complete_pair(intent, fees, now_ms, mode=mode)
        return self._naked_leg(
            intent, fees, now_ms, filled_side="YES", book=yes
        )

    def _canceled(self, intent: Intent, fees: MarketFees) -> PaperFillResult:
        pair_fees = pair_fees_for_intent(intent, fees)
        return PaperFillResult(
            accepted=True,
            reject_reason=None,
            size=intent.size,
            yes_vwap=intent.gap.yes_vwap,
            no_vwap=intent.gap.no_vwap,
            pair_fees=pair_fees,
            cost=pair_cost(intent, fees),
            pnl=_ZERO,
            bankroll=self.bankroll,
            daily_pnl=self.daily_pnl,
            path=intent.path,
            condition_id=intent.gap.condition_id,
            outcome="canceled",
            naked=False,
            hedge_pnl=_ZERO,
            completed=False,
        )

    async def poll_rests(self, store: BookStore, now_ms: int) -> list[PaperFillResult]:
        """Settle or expire maker rests. No live cancel."""
        results: list[PaperFillResult] = []
        still: list[RestingPair] = []
        for rest in self._rests:
            yes = store.get(rest.intent.gap.yes_token_id)
            no = store.get(rest.intent.gap.no_token_id)
            timed_out = now_ms - rest.posted_ms >= self.maker_rest_ms
            if yes is None or no is None:
                # Window swap / retain drops books. Do not hold the
                # max_open_pairs slot forever; no book means no honest fill.
                if timed_out:
                    results.append(self._canceled(rest.intent, rest.fees))
                else:
                    still.append(rest)
                continue
            yes_ok = _maker_side_fills(
                rest.posted_yes, yes, rest.intent.yes_limit, timed_out
            )
            no_ok = _maker_side_fills(
                rest.posted_no, no, rest.intent.no_limit, timed_out
            )
            if yes_ok and no_ok:
                results.append(
                    await self._complete_pair(
                        rest.intent, rest.fees, now_ms, mode="paper"
                    )
                )
                continue
            if not timed_out:
                still.append(rest)
                continue
            yes_taken = _maker_side_taken(rest.posted_yes, yes, rest.intent.yes_limit)
            no_taken = _maker_side_taken(rest.posted_no, no, rest.intent.no_limit)
            if yes_taken and no_taken:
                results.append(
                    await self._complete_pair(
                        rest.intent, rest.fees, now_ms, mode="paper"
                    )
                )
                continue
            if yes_taken or no_taken:
                # Only a shown take is a naked. Still-at-bid on one side
                # while the other moved is a cancel, not a hedge.
                filled_side = "YES" if yes_taken else "NO"
                book = yes if filled_side == "YES" else no
                results.append(
                    self._naked_leg(
                        rest.intent,
                        rest.fees,
                        now_ms,
                        filled_side=filled_side,
                        book=book,
                    )
                )
                continue
            results.append(self._canceled(rest.intent, rest.fees))
        self._rests = still
        return results
