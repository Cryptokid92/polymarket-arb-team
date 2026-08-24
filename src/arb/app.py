"""Paper pipeline and paper-only run loop. No secure client. No network imports."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from arb.books import Book, BookStore
from arb.config import Settings
from arb.executor import PaperBroker, PaperOrder
from arb.fee_agent import MarketFees, choose_intent
from arb.fees import net_edge_maker, net_edge_taker, pair_taker_fees
from arb.hunter import hunt
from arb.killswitch import KillSwitch
from arb.messages import GapFound, Intent
from arb.risk import MarketFlags, Portfolio, approve
from arb.state import StateStore

_TAKER_BUFFER = Decimal("0.005")
_MAX_SHARES = Decimal("1000000")
_SHORT_WINDOW = re.compile(
    r"(?:^|[^0-9])(?:5|15)(?:\s|-)?(?:m(?:in(?:ute)?s?)?)\b",
    re.IGNORECASE,
)


class PublicApiError(RuntimeError):
    """Public API is unreachable. The paper runner does not fake gaps."""


@dataclass
class PipelineTrace:
    gap: GapFound | None
    intent: Intent | None
    reject_reason: str | None
    maker_ev: Decimal | None
    taker_ev: Decimal | None


@dataclass
class UniversePair:
    condition_id: str
    yes_token_id: str
    no_token_id: str
    flags: MarketFlags
    fees: MarketFees


@dataclass
class PaperRunStats:
    markets_listed: int = 0
    universe: int = 0
    gaps: int = 0
    intents: int = 0
    rejects: dict[str, int] = field(default_factory=dict)


def run_pipeline(
    yes: Book,
    no: Book,
    settings: Settings,
    market_flags: MarketFlags,
    fees: MarketFees,
    portfolio: Portfolio,
    now_ms: int,
) -> Intent | None:
    return run_pipeline_traced(
        yes, no, settings, market_flags, fees, portfolio, now_ms
    ).intent


def run_pipeline_traced(
    yes: Book,
    no: Book,
    settings: Settings,
    market_flags: MarketFlags,
    fees: MarketFees,
    portfolio: Portfolio,
    now_ms: int,
) -> PipelineTrace:
    min_size = (
        yes.min_order_size
        if yes.min_order_size >= no.min_order_size
        else no.min_order_size
    )
    gap = hunt(yes, no, settings.min_edge, min_size, _MAX_SHARES, now_ms)
    if gap is None:
        return PipelineTrace(None, None, None, None, None)
    maker_ev, taker_ev = _estimate_ev(gap, fees)
    reason = _approve_reject_reason(gap, portfolio, settings, market_flags)
    if reason is not None:
        return PipelineTrace(gap, None, reason, maker_ev, taker_ev)
    approved = approve(gap, portfolio, settings, market_flags)
    if approved is None:
        return PipelineTrace(gap, None, "risk_rejected", maker_ev, taker_ev)
    intent = choose_intent(approved, fees, settings.min_edge)
    if intent is None:
        return PipelineTrace(approved, None, "fee_ev_nonpositive", maker_ev, taker_ev)
    return PipelineTrace(approved, intent, None, maker_ev, taker_ev)


async def paper_execute(
    intent: Intent, broker: PaperBroker
) -> tuple[PaperOrder, PaperOrder]:
    return await broker.post_pair(intent)


def _estimate_ev(gap: GapFound, fees: MarketFees) -> tuple[Decimal, Decimal]:
    size = gap.fillable_shares
    maker_ev = net_edge_maker(gap.raw_edge, size)
    pair_fees = pair_taker_fees(
        size, gap.yes_vwap, size, gap.no_vwap, fees.yes_rate, fees.no_rate
    )
    taker_ev = net_edge_taker(gap.raw_edge, size, pair_fees) - (_TAKER_BUFFER * size)
    return maker_ev, taker_ev


def _approve_reject_reason(
    gap: GapFound,
    portfolio: Portfolio,
    settings: Settings,
    market_flags: MarketFlags,
) -> str | None:
    if portfolio.halted:
        return "halted"
    if not market_flags.binary:
        return "not_binary"
    if not market_flags.accepting_orders:
        return "not_accepting"
    if market_flags.seconds_delay > 0:
        return "seconds_delay"
    if market_flags.neg_risk:
        return "neg_risk"
    if gap.book_age_ms > settings.stale_ms:
        return "stale"
    if gap.raw_edge > settings.max_gap:
        return "max_gap"
    if portfolio.open_pairs >= settings.max_open_pairs:
        return "max_open_pairs"
    if portfolio.daily_pnl <= -settings.max_daily_loss:
        return "daily_loss"
    return None


def reject_universe(market: Any) -> str | None:
    """Return a reject reason or None if the market is in the v1 universe."""
    state = getattr(market, "state", None)
    trading = getattr(market, "trading", None)
    outcomes = getattr(market, "outcomes", None)
    if getattr(state, "closed", False) or getattr(state, "archived", False):
        return "closed"
    if not getattr(state, "accepting_orders", False):
        return "not_accepting"
    if getattr(state, "neg_risk", False):
        return "neg_risk"
    delay = getattr(trading, "seconds_delay", 0) or 0
    if delay > 0:
        return "seconds_delay"
    yes = getattr(outcomes, "yes", None)
    no = getattr(outcomes, "no", None)
    yes_id = getattr(yes, "token_id", None)
    no_id = getattr(no, "token_id", None)
    if not yes_id or not no_id:
        return "not_binary"
    if _is_short_crypto_window(market):
        return "short_crypto_window"
    return None


def _is_short_crypto_window(market: Any) -> bool:
    parts = [
        getattr(market, "slug", None),
        getattr(market, "question", None),
        getattr(market, "group_item_title", None),
        getattr(market, "category", None),
    ]
    for tag in getattr(market, "tags", ()) or ():
        parts.append(getattr(tag, "slug", None))
        parts.append(getattr(tag, "label", None))
    blob = " ".join(str(part) for part in parts if part)
    if not _SHORT_WINDOW.search(blob):
        return False
    lowered = blob.lower()
    crypto_hints = ("crypto", "btc", "eth", "bitcoin", "ethereum", "updown", "up-or-down")
    return any(hint in lowered for hint in crypto_hints)


def universe_pair(market: Any) -> UniversePair:
    yes_id = str(market.outcomes.yes.token_id)
    no_id = str(market.outcomes.no.token_id)
    trading = getattr(market, "trading", None)
    schedule = getattr(trading, "fee_schedule", None)
    rate = getattr(schedule, "rate", None)
    fee_rate = rate if type(rate) is Decimal else Decimal("0")
    return UniversePair(
        condition_id=str(getattr(market, "condition_id", "") or ""),
        yes_token_id=yes_id,
        no_token_id=no_id,
        flags=MarketFlags(
            accepting_orders=True,
            seconds_delay=int(getattr(trading, "seconds_delay", 0) or 0),
            neg_risk=False,
            binary=True,
        ),
        fees=MarketFees(yes_rate=fee_rate, no_rate=fee_rate),
    )


def orderbook_to_payload(book: Any, *, now_ms: int) -> dict[str, Any]:
    ts = getattr(book, "timestamp", None)
    if ts is not None and hasattr(ts, "timestamp"):
        ts_ms = int(ts.timestamp() * 1000)
    else:
        ts_ms = int(getattr(book, "ts_ms", now_ms) or now_ms)
    tick = getattr(book, "tick_size", None) or getattr(book, "tick", Decimal("0.01"))
    min_size = getattr(book, "min_order_size", Decimal("5"))
    return {
        "token_id": str(getattr(book, "token_id", "") or getattr(book, "asset_id", "")),
        "bids": [
            {"price": str(level.price), "size": str(level.size)}
            for level in getattr(book, "bids", ()) or ()
        ],
        "asks": [
            {"price": str(level.price), "size": str(level.size)}
            for level in getattr(book, "asks", ()) or ()
        ],
        "tick": str(tick),
        "min_order_size": str(min_size),
        "ts_ms": ts_ms,
        "hash": getattr(book, "hash", None),
    }


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _bump(stats: PaperRunStats, reason: str) -> None:
    stats.rejects[reason] = stats.rejects.get(reason, 0) + 1


def write_paper_stats(path: Path, stats: PaperRunStats) -> None:
    """Atomic snapshot for the read-only paper UI. No account data."""
    payload = {
        "markets_listed": stats.markets_listed,
        "universe": stats.universe,
        "gaps": stats.gaps,
        "intents": stats.intents,
        "rejects": sum(stats.rejects.values()),
        "reject_reasons": dict(stats.rejects),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    tmp.replace(path)


async def _iter_listed_markets(client: Any, max_markets: int) -> list[Any]:
    try:
        listed = client.list_markets(closed=False, page_size=max_markets)
        if inspect.isawaitable(listed):
            listed = await listed
    except PublicApiError:
        raise
    except Exception as exc:
        raise PublicApiError(f"public API is unreachable: {exc}") from exc

    items: list[Any] = []
    iter_items = getattr(listed, "iter_items", None)
    if callable(iter_items):
        async for market in iter_items():
            items.append(market)
            if len(items) >= max_markets:
                break
        return items
    if isinstance(listed, list):
        return listed[:max_markets]
    raise PublicApiError("public API is unreachable: list_markets returned no page")


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


async def _fetch_books(client: Any, token_ids: Sequence[str]) -> Any:
    try:
        books = client.get_order_books(token_ids=list(token_ids))
        if inspect.isawaitable(books):
            books = await books
        return books
    except PublicApiError:
        raise
    except Exception as exc:
        raise PublicApiError(f"public API is unreachable: {exc}") from exc


async def _updates(
    client: Any,
    token_ids: Sequence[str],
    poll_s: float,
) -> AsyncIterator[Any]:
    subscribe = getattr(client, "subscribe", None)
    if callable(subscribe):
        stream = subscribe(list(token_ids))
        if inspect.isawaitable(stream):
            stream = await stream
        async for event in stream:
            yield event
        return
    while True:
        yield await _fetch_books(client, token_ids)
        await asyncio.sleep(poll_s)


def _apply_update(store: BookStore, update: Any, now_ms: int) -> None:
    if isinstance(update, (list, tuple)):
        for book in update:
            store.apply_snapshot(orderbook_to_payload(book, now_ms=now_ms))
        return
    typ = getattr(update, "type", None)
    payload = getattr(update, "payload", None)
    if typ == "book" and payload is not None:
        store.apply_snapshot(orderbook_to_payload(payload, now_ms=now_ms))
        return
    if typ == "price_change" and payload is not None:
        changes = []
        for change in getattr(payload, "price_changes", ()) or ():
            changes.append(
                {
                    "token_id": str(change.token_id),
                    "price": str(change.price),
                    "size": str(change.size),
                    "side": change.side,
                    "hash": getattr(change, "hash", None),
                }
            )
        ts = getattr(payload, "timestamp", None)
        ts_ms = int(ts.timestamp() * 1000) if ts is not None and hasattr(ts, "timestamp") else now_ms
        store.apply_price_change({"ts_ms": ts_ms, "price_changes": changes})
        return
    if hasattr(update, "token_id") and hasattr(update, "asks"):
        store.apply_snapshot(orderbook_to_payload(update, now_ms=now_ms))


async def run_paper(
    *,
    client: Any,
    settings: Settings,
    project_root: Path,
    data_dir: Path,
    seconds: int = 3600,
    max_markets: int = 20,
    once: bool = False,
    poll_s: float = 0.4,
) -> PaperRunStats:
    """Hunt → risk → fee → paper executor. Never places live orders."""
    if settings.arb_mode == "live":
        raise RuntimeError("paper_run is paper-only and will not place live orders")

    gaps_path = data_dir / "gaps.jsonl"
    intents_path = data_dir / "intents.jsonl"
    rejects_path = data_dir / "rejects.jsonl"
    stats_path = data_dir / "stats.json"
    stats = PaperRunStats()
    store = BookStore()
    broker = PaperBroker(log_path=intents_path)
    kill = KillSwitch(
        project_root=project_root,
        state=StateStore(data_dir / "state.sqlite"),
        settings=settings,
    )
    portfolio = Portfolio(
        yes={}, no={}, open_pairs=0, daily_pnl=Decimal("0"), halted=False
    )

    markets = await _iter_listed_markets(client, max_markets)
    stats.markets_listed = len(markets)
    pairs: list[UniversePair] = []
    by_token: dict[str, UniversePair] = {}
    for market in markets:
        reason = reject_universe(market)
        if reason is not None:
            _append_jsonl(
                rejects_path,
                {
                    "ts_ms": _now_ms(),
                    "condition_id": str(getattr(market, "condition_id", "") or ""),
                    "reason": reason,
                },
            )
            _bump(stats, reason)
            continue
        pair = universe_pair(market)
        pairs.append(pair)
        by_token[pair.yes_token_id] = pair
        by_token[pair.no_token_id] = pair
    stats.universe = len(pairs)
    write_paper_stats(stats_path, stats)

    async def consider(pair: UniversePair) -> None:
        yes = store.get(pair.yes_token_id)
        no = store.get(pair.no_token_id)
        if yes is None or no is None:
            return
        now_ms = _now_ms()
        portfolio.halted = not kill.allow_new_intents()
        kill.evaluate(
            daily_pnl=portfolio.daily_pnl,
            ws_age_ms=max(0, now_ms - min(yes.ts_ms, no.ts_ms)),
            now_ms=now_ms,
        )
        portfolio.halted = not kill.allow_new_intents()
        trace = run_pipeline_traced(
            yes, no, settings, pair.flags, pair.fees, portfolio, now_ms
        )
        if trace.gap is not None:
            stats.gaps += 1
            _append_jsonl(
                gaps_path,
                {
                    "ts_ms": now_ms,
                    "condition_id": pair.condition_id,
                    "raw_edge": str(trace.gap.raw_edge),
                    "yes_vwap": str(trace.gap.yes_vwap),
                    "no_vwap": str(trace.gap.no_vwap),
                    "fillable_shares": str(trace.gap.fillable_shares),
                    "book_age_ms": trace.gap.book_age_ms,
                    "maker_ev": str(trace.maker_ev) if trace.maker_ev is not None else None,
                    "taker_ev": str(trace.taker_ev) if trace.taker_ev is not None else None,
                    "reject_reason": trace.reject_reason,
                },
            )
        if trace.reject_reason:
            _append_jsonl(
                rejects_path,
                {
                    "ts_ms": now_ms,
                    "condition_id": pair.condition_id,
                    "reason": trace.reject_reason,
                },
            )
            _bump(stats, trace.reject_reason)
        if trace.intent is not None:
            await paper_execute(trace.intent, broker)
            stats.intents += 1
            portfolio.open_pairs += 1
        write_paper_stats(stats_path, stats)

    token_ids = [token for pair in pairs for token in (pair.yes_token_id, pair.no_token_id)]
    if token_ids:
        books = await _fetch_books(client, token_ids)
        _apply_update(store, books, _now_ms())
        for pair in pairs:
            await consider(pair)

    if once or not token_ids:
        write_paper_stats(stats_path, stats)
        return stats

    deadline = time.monotonic() + seconds
    async for update in _updates(client, token_ids, poll_s):
        _apply_update(store, update, _now_ms())
        seen: set[str] = set()
        if isinstance(update, (list, tuple)):
            tokens = [str(getattr(book, "token_id", "")) for book in update]
        else:
            payload = getattr(update, "payload", update)
            token = getattr(payload, "token_id", None)
            tokens = [str(token)] if token else list(by_token)
            for change in getattr(payload, "price_changes", ()) or ():
                tokens.append(str(change.token_id))
        for token in tokens:
            pair = by_token.get(token)
            if pair is None or pair.condition_id in seen:
                continue
            seen.add(pair.condition_id)
            await consider(pair)
        if time.monotonic() >= deadline:
            break
    write_paper_stats(stats_path, stats)
    return stats
