"""Replay recorded books. Fill on ask/bid depth, never last-trade or mid."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal

from arb.books import Book, Level, _reject_float, consume_levels, walk_asks
from arb.fees import pair_taker_fees, taker_fee
from arb.hunter import hunt
from arb.maker import maker_complete_quotes
from arb.merge import mergeable
from arb.naked_leg import hedge_plan
from arb.nearmiss import NearMissTracker, measure_pair
from arb.recorder import BookFrame, events_by_condition, frames_from_events

_ONE = Decimal("1")
_ZERO = Decimal("0")


def walk_bids(bids: list[Level], shares: Decimal) -> tuple[Decimal, Decimal] | None:
    """Sell `shares` into bids (best first). None if depth is insufficient."""
    shares = _reject_float(shares, "shares")
    if shares <= 0:
        return None
    remaining = shares
    notional = _ZERO
    for level in bids:
        if level.size <= 0:
            continue
        take = remaining if remaining <= level.size else level.size
        notional += take * level.price
        remaining -= take
        if remaining == 0:
            return (notional / shares, shares)
    return None


def _best_bid(book: Book) -> Decimal:
    return book.bids[0].price if book.bids else _ZERO


def _best_ask(book: Book) -> Decimal:
    return book.asks[0].price if book.asks else _ONE


def _ask_size_at(book: Book, price: Decimal) -> Decimal:
    return sum((lvl.size for lvl in book.asks if lvl.price == price), _ZERO)


class _MissRng:
    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def second_fak_misses(self, p_miss: Decimal) -> bool:
        p_miss = _reject_float(p_miss, "p_miss")
        if p_miss <= _ZERO:
            return False
        if p_miss >= _ONE:
            return True
        thresh = int(p_miss * Decimal("10000"))
        return self._rng.randrange(10000) < thresh


@dataclass
class BacktestConfig:
    path: Literal["taker_fak", "maker_gtc"] = "taker_fak"
    p_miss: Decimal = Decimal("0.3")
    latency_ms: int = 100
    maker_rest_ms: int = 400
    hedge_slippage: Decimal = Decimal("0.01")
    fee_rate_yes: Decimal = Decimal("0")
    fee_rate_no: Decimal = Decimal("0")
    min_edge: Decimal = Decimal("0.01")
    min_size: Decimal = Decimal("5")
    max_shares: Decimal = Decimal("80")
    starting_capital: Decimal = Decimal("100")
    rng_seed: int = 0
    maker_complete: bool = True
    max_gap: Decimal = Decimal("0.08")
    stale_ms: int = 400
    max_notional: Decimal = Decimal("25")


@dataclass
class FillRecord:
    ts_ms: int
    decision_ts_ms: int
    book_ts_ms: int
    side: Literal["YES", "NO"]
    size: Decimal
    price: Decimal
    kind: str
    fill_source: Literal["ask", "bid", "mid"]
    best_bid: Decimal
    best_ask: Decimal
    ask_vwap: Decimal | None


@dataclass
class DecisionRecord:
    t_ms: int
    yes_book_ts_ms: int
    no_book_ts_ms: int


@dataclass
class BacktestResult:
    trades: int
    completed_pairs: int
    naked_incidents: int
    net_pnl: Decimal
    capital_turns: Decimal
    fills: list[FillRecord] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)


def _frame_at_or_before(frames: Sequence[BookFrame], ts_ms: int) -> BookFrame | None:
    chosen: BookFrame | None = None
    for frame in frames:
        if frame.ts_ms <= ts_ms:
            chosen = frame
        else:
            break
    return chosen


def _limit_buy_fill(
    *,
    book: Book,
    size: Decimal,
    price: Decimal,
    ts_ms: int,
    decision_ts_ms: int,
    side: Literal["YES", "NO"],
    kind: str,
) -> FillRecord:
    """Fill a resting buy at its limit. Not an ask walk. Not mid."""
    price = _reject_float(price, "limit")
    return FillRecord(
        ts_ms=ts_ms,
        decision_ts_ms=decision_ts_ms,
        book_ts_ms=book.ts_ms,
        side=side,
        size=size,
        price=price,
        kind=kind,
        fill_source="bid",
        best_bid=_best_bid(book),
        best_ask=_best_ask(book),
        ask_vwap=None,
    )


def _buy_fill(
    *,
    book: Book,
    size: Decimal,
    ts_ms: int,
    decision_ts_ms: int,
    side: Literal["YES", "NO"],
    kind: str,
) -> FillRecord | None:
    walked = walk_asks(book.asks, size)
    if walked is None:
        return None
    vwap, _filled = walked
    return FillRecord(
        ts_ms=ts_ms,
        decision_ts_ms=decision_ts_ms,
        book_ts_ms=book.ts_ms,
        side=side,
        size=size,
        price=vwap,
        kind=kind,
        fill_source="ask",
        best_bid=_best_bid(book),
        best_ask=_best_ask(book),
        ask_vwap=vwap,
    )


def _maker_side_taken(posted: Book, now: Book, limit: Decimal) -> bool:
    """True when the book shows a take at our limit. Still-at-bid is not a take."""
    if not now.asks:
        return False
    if _ask_size_at(now, limit) < _ask_size_at(posted, limit):
        return True
    return now.asks[0].price <= limit


def _maker_side_fills(
    posted: Book,
    now: Book,
    limit: Decimal,
    rested: bool,
) -> bool:
    if not rested:
        return False
    return _maker_side_taken(posted, now, limit)


def _book_after_takes(book: Book, *, ask_taken: Decimal, bid_taken: Decimal) -> Book:
    return book.model_copy(
        update={
            "asks": consume_levels(book.asks, ask_taken, asks=True),
            "bids": consume_levels(book.bids, bid_taken, asks=False),
        }
    )


def _note_taken(
    ask_taken: dict[str, Decimal],
    bid_taken: dict[str, Decimal],
    token_id: str,
    fill: FillRecord,
) -> None:
    bucket = ask_taken if fill.fill_source == "ask" else bid_taken
    bucket[token_id] = bucket.get(token_id, _ZERO) + fill.size


def _hedge_fill(
    *,
    book: Book,
    size: Decimal,
    side: Literal["YES", "NO"],
    ts_ms: int,
    decision_ts_ms: int,
    slippage: Decimal,
) -> tuple[FillRecord, Decimal]:
    walked = walk_bids(book.bids, size)
    bid_vwap = walked[0] if walked is not None else _ZERO
    px = bid_vwap - slippage
    if px < _ZERO:
        px = _ZERO
    fill = FillRecord(
        ts_ms=ts_ms,
        decision_ts_ms=decision_ts_ms,
        book_ts_ms=book.ts_ms,
        side=side,
        size=size,
        price=px,
        kind="hedge",
        fill_source="bid",
        best_bid=_best_bid(book),
        best_ask=_best_ask(book),
        ask_vwap=None,
    )
    return fill, px * size


def run_backtest(
    events: Sequence[dict],
    config: BacktestConfig | None = None,
    *,
    keep_trace: bool = True,
) -> BacktestResult:
    cfg = config or BacktestConfig()
    frames = frames_from_events(events)
    rng = _MissRng(cfg.rng_seed)
    fills: list[FillRecord] = []
    decisions: list[DecisionRecord] = []
    completed = 0
    naked = 0
    trades = 0
    pnl = _ZERO
    buy_notional = _ZERO

    ask_taken: dict[str, Decimal] = {}
    bid_taken: dict[str, Decimal] = {}
    i = 0
    while i < len(frames):
        frame = frames[i]
        if keep_trace:
            decisions.append(
                DecisionRecord(
                    t_ms=frame.ts_ms,
                    yes_book_ts_ms=frame.yes.ts_ms,
                    no_book_ts_ms=frame.no.ts_ms,
                )
            )
        yes = _book_after_takes(
            frame.yes,
            ask_taken=ask_taken.get(frame.yes.token_id, _ZERO),
            bid_taken=bid_taken.get(frame.yes.token_id, _ZERO),
        )
        no = _book_after_takes(
            frame.no,
            ask_taken=ask_taken.get(frame.no.token_id, _ZERO),
            bid_taken=bid_taken.get(frame.no.token_id, _ZERO),
        )
        gap = hunt(
            yes,
            no,
            cfg.min_edge,
            cfg.min_size,
            cfg.max_shares,
            now_ms=frame.ts_ms,
        )
        quotes = None
        if gap is None and cfg.maker_complete:
            quotes = maker_complete_quotes(
                yes,
                no,
                min_edge=cfg.min_edge,
                max_gap=cfg.max_gap,
                min_size=cfg.min_size,
                max_notional=cfg.max_notional,
                stale_ms=cfg.stale_ms,
                now_ms=frame.ts_ms,
            )
        if gap is None and quotes is None:
            i += 1
            continue

        path = "maker_gtc" if quotes is not None else "taker_fak"
        yes_limit = quotes.yes_bid if quotes is not None else gap.yes_vwap
        no_limit = quotes.no_bid if quotes is not None else gap.no_vwap
        size = quotes.size if quotes is not None else gap.fillable_shares
        delay = cfg.maker_rest_ms if path == "maker_gtc" else cfg.latency_ms
        exec_ts = frame.ts_ms + delay
        raw_exec = _frame_at_or_before(frames, exec_ts) or frame
        exec_frame_yes = _book_after_takes(
            raw_exec.yes,
            ask_taken=ask_taken.get(raw_exec.yes.token_id, _ZERO),
            bid_taken=bid_taken.get(raw_exec.yes.token_id, _ZERO),
        )
        exec_frame_no = _book_after_takes(
            raw_exec.no,
            ask_taken=ask_taken.get(raw_exec.no.token_id, _ZERO),
            bid_taken=bid_taken.get(raw_exec.no.token_id, _ZERO),
        )

        if path == "maker_gtc":
            rested = exec_ts - frame.ts_ms >= cfg.maker_rest_ms
            yes_ok = _maker_side_fills(yes, exec_frame_yes, yes_limit, rested)
            no_ok = _maker_side_fills(no, exec_frame_no, no_limit, rested)
            yes_fill = (
                _limit_buy_fill(
                    book=exec_frame_yes,
                    size=size,
                    price=yes_limit,
                    ts_ms=exec_ts,
                    decision_ts_ms=frame.ts_ms,
                    side="YES",
                    kind=path,
                )
                if yes_ok
                else None
            )
            no_fill = (
                _limit_buy_fill(
                    book=exec_frame_no,
                    size=size,
                    price=no_limit,
                    ts_ms=exec_ts,
                    decision_ts_ms=frame.ts_ms,
                    side="NO",
                    kind=path,
                )
                if no_ok
                else None
            )
        else:
            yes_fill = _buy_fill(
                book=exec_frame_yes,
                size=size,
                ts_ms=exec_ts,
                decision_ts_ms=frame.ts_ms,
                side="YES",
                kind=path,
            )
            no_fill = None
            if yes_fill is not None and not rng.second_fak_misses(cfg.p_miss):
                no_fill = _buy_fill(
                    book=exec_frame_no,
                    size=size,
                    ts_ms=exec_ts,
                    decision_ts_ms=frame.ts_ms,
                    side="NO",
                    kind=path,
                )

        if yes_fill is None and no_fill is None:
            i += 1
            continue

        trades += 1
        yes_sz = yes_fill.size if yes_fill is not None else _ZERO
        no_sz = no_fill.size if no_fill is not None else _ZERO
        if yes_fill is not None:
            if keep_trace:
                fills.append(yes_fill)
            buy_notional += yes_fill.price * yes_fill.size
            _note_taken(ask_taken, bid_taken, yes.token_id, yes_fill)
        if no_fill is not None:
            if keep_trace:
                fills.append(no_fill)
            buy_notional += no_fill.price * no_fill.size
            _note_taken(ask_taken, bid_taken, no.token_id, no_fill)

        fees = _ZERO
        if path == "taker_fak":
            if yes_fill is not None:
                fees += taker_fee(yes_fill.size, yes_fill.price, cfg.fee_rate_yes)
            if no_fill is not None:
                fees += taker_fee(no_fill.size, no_fill.price, cfg.fee_rate_no)

        merged = mergeable(yes_sz, no_sz)
        if merged > _ZERO and yes_fill is not None and no_fill is not None:
            pair_fees = (
                pair_taker_fees(
                    merged,
                    yes_fill.price,
                    merged,
                    no_fill.price,
                    cfg.fee_rate_yes,
                    cfg.fee_rate_no,
                )
                if path == "taker_fak"
                else _ZERO
            )
            pnl += merged - (yes_fill.price * merged) - (no_fill.price * merged)
            pnl -= pair_fees
            completed += 1
            leftover_yes = yes_sz - merged
            leftover_no = no_sz - merged
            fees = _ZERO  # already applied as pair_fees
        else:
            leftover_yes = yes_sz
            leftover_no = no_sz
            pnl -= fees

        plan = hedge_plan(leftover_yes, leftover_no)
        if plan is not None:
            naked += 1
            hedge_book = exec_frame_yes if plan.side == "YES" else exec_frame_no
            buy_px = (
                yes_fill.price
                if plan.side == "YES" and yes_fill is not None
                else no_fill.price
                if no_fill is not None
                else _ZERO
            )
            hedge, proceeds = _hedge_fill(
                book=hedge_book,
                size=plan.size,
                side=plan.side,
                ts_ms=exec_ts,
                decision_ts_ms=frame.ts_ms,
                slippage=cfg.hedge_slippage,
            )
            if keep_trace:
                fills.append(hedge)
            _note_taken(ask_taken, bid_taken, hedge_book.token_id, hedge)
            pnl += proceeds - (buy_px * plan.size)

        i += 1
        while i < len(frames) and frames[i].ts_ms <= exec_ts:
            i += 1

    capital = cfg.starting_capital
    turns = buy_notional / capital if capital > _ZERO else _ZERO
    return BacktestResult(
        trades=trades,
        completed_pairs=completed,
        naked_incidents=naked,
        net_pnl=pnl,
        capital_turns=turns,
        fills=fills,
        decisions=decisions,
    )


def analyze_tape_edges(
    events: Sequence[dict],
    *,
    min_edge: Decimal = Decimal("0.01"),
    min_size: Decimal = Decimal("5"),
    max_shares: Decimal = Decimal("80"),
    max_gap: Decimal = Decimal("0.08"),
    stale_ms: int = 400,
    max_notional: Decimal = Decimal("25"),
) -> dict[str, object]:
    """Miss vs absence: did any frame have an ask VWAP sum <= 1 - min_edge?"""
    frames = frames_from_events(events)
    tracker = NearMissTracker()
    ask_gap_frames = 0
    maker_frames = 0
    for frame in frames:
        min_sz = frame.yes.min_order_size
        if frame.no.min_order_size > min_sz:
            min_sz = frame.no.min_order_size
        if min_sz < min_size:
            min_sz = min_size
        miss = measure_pair(
            frame.yes,
            frame.no,
            min_sz,
            max_shares,
            frame.ts_ms,
            condition_id="",
            in_watch=True,
        )
        tracker.observe(miss)
        if miss.raw_edge is not None and miss.raw_edge >= min_edge:
            ask_gap_frames += 1
        quotes = maker_complete_quotes(
            frame.yes,
            frame.no,
            min_edge=min_edge,
            max_gap=max_gap,
            min_size=min_sz,
            max_notional=max_notional,
            stale_ms=stale_ms,
            now_ms=frame.ts_ms,
        )
        if quotes is not None:
            maker_frames += 1
    snap = tracker.snapshot()
    decision = "capture" if ask_gap_frames > 0 else "maker_completeness"
    return {
        "frames": len(frames),
        "ask_gap_frames": ask_gap_frames,
        "maker_quote_frames": maker_frames,
        "best_ask_edge": snap["best_edge"],
        "edge_histogram": snap["edge_histogram"],
        "edge_thresholds": snap["edge_thresholds"],
        "decision": decision,
    }


def summarize_tape(
    events: Sequence[dict],
    config: BacktestConfig | None = None,
) -> dict[str, object]:
    """Replay a recorded hour tape. Does not loosen hunt/risk. No live path."""
    if not events:
        return {
            "events": 0,
            "trades": 0,
            "completed_pairs": 0,
            "naked_incidents": 0,
            "net_pnl": "0",
            "capital_turns": "0",
            "verdict": "no_tape",
        }
    result = run_backtest(events, config)
    verdict = "positive" if result.net_pnl > _ZERO else "non_positive"
    return {
        "events": len(events),
        "trades": result.trades,
        "completed_pairs": result.completed_pairs,
        "naked_incidents": result.naked_incidents,
        "net_pnl": str(result.net_pnl),
        "capital_turns": str(result.capital_turns),
        "verdict": verdict,
    }


def replay_tape_path(
    path: Path,
    config: BacktestConfig | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Analyze + backtest one condition at a time. Do not load a 1GB tape."""
    cfg = config or BacktestConfig()
    tracker = NearMissTracker()
    frames_n = 0
    ask_gap_frames = 0
    maker_frames = 0
    events_n = 0
    trades = 0
    completed = 0
    naked = 0
    pnl = _ZERO
    buy_notional = _ZERO
    saw_any = False
    for _cid, events in events_by_condition(path):
        saw_any = True
        events_n += len(events)
        frames = frames_from_events(events)
        frames_n += len(frames)
        for frame in frames:
            min_sz = frame.yes.min_order_size
            if frame.no.min_order_size > min_sz:
                min_sz = frame.no.min_order_size
            if min_sz < cfg.min_size:
                min_sz = cfg.min_size
            miss = measure_pair(
                frame.yes,
                frame.no,
                min_sz,
                cfg.max_shares,
                frame.ts_ms,
                condition_id="",
                in_watch=True,
            )
            tracker.observe(miss)
            if miss.raw_edge is not None and miss.raw_edge >= cfg.min_edge:
                ask_gap_frames += 1
            quotes = maker_complete_quotes(
                frame.yes,
                frame.no,
                min_edge=cfg.min_edge,
                max_gap=cfg.max_gap,
                min_size=min_sz,
                max_notional=cfg.max_notional,
                stale_ms=cfg.stale_ms,
                now_ms=frame.ts_ms,
            )
            if quotes is not None:
                maker_frames += 1
        result = run_backtest(events, cfg, keep_trace=False)
        trades += result.trades
        completed += result.completed_pairs
        naked += result.naked_incidents
        pnl += result.net_pnl
        buy_notional += result.capital_turns * cfg.starting_capital
    if not saw_any:
        return (
            {
                "frames": 0,
                "ask_gap_frames": 0,
                "maker_quote_frames": 0,
                "best_ask_edge": None,
                "edge_histogram": {},
                "edge_thresholds": {},
                "decision": "maker_completeness",
            },
            {
                "events": 0,
                "trades": 0,
                "completed_pairs": 0,
                "naked_incidents": 0,
                "net_pnl": "0",
                "capital_turns": "0",
                "verdict": "no_tape",
            },
        )
    snap = tracker.snapshot()
    decision = "capture" if ask_gap_frames > 0 else "maker_completeness"
    capital = cfg.starting_capital
    turns = buy_notional / capital if capital > _ZERO else _ZERO
    analysis = {
        "frames": frames_n,
        "ask_gap_frames": ask_gap_frames,
        "maker_quote_frames": maker_frames,
        "best_ask_edge": snap["best_edge"],
        "edge_histogram": snap["edge_histogram"],
        "edge_thresholds": snap["edge_thresholds"],
        "decision": decision,
    }
    summary = {
        "events": events_n,
        "trades": trades,
        "completed_pairs": completed,
        "naked_incidents": naked,
        "net_pnl": str(pnl),
        "capital_turns": str(turns),
        "verdict": "positive" if pnl > _ZERO else "non_positive",
    }
    return analysis, summary
