"""Paper pipeline and paper-only run loop. No secure client. No network imports."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from arb.alerts import alert_record
from arb.books import Book, BookStore
from arb.config import Settings
from arb.executor import PaperBroker, PaperOrder
from arb.fee_agent import MarketFees, choose_intent
from arb.fees import net_edge_maker, net_edge_taker, pair_taker_fees
from arb.hunter import hunt
from arb.killswitch import KillSwitch
from arb.messages import GapFound, Intent
from arb.nearmiss import NearMiss, NearMissTracker, measure_pair
from arb.paper_control import (
    clear_pid,
    effective_rotate_s,
    read_control,
    write_pid,
)
from arb.paper_ledger import PaperFillResult, PaperLedger
from arb.recorder import BookRecorder, book_to_event
from arb.risk import MarketFlags, Portfolio, approve
from arb.state import StateStore
from arb.watch import hot_watch_slice

_TAKER_BUFFER = Decimal("0.005")
_MAX_SHARES = Decimal("1000000")
# Official list_markets page size. Do not pass max_markets as page_size.
LIST_PAGE_SIZE = 100
# Documented ceiling for --all-markets / --max-markets 0.
# Do not raise this as a payload-limit fix; listing is already paginated.
LIST_SAFETY_CAP = 5000
# REST get_order_books token-id batch. Hour-6 --all-markets died on one
# request of ~3080 ids ("Payload exceeds the limit"). 50 stays under
# official CLOB payload limits.
BOOK_BATCH_SIZE = 50
# Live subscribe/poll window. 40 pairs = 80 token ids. Do not subscribe
# all ~1540 universe pairs at once.
WATCH_PAIRS = 40
# Pin this many highest-edge pairs inside WATCH_PAIRS. Do not raise the cap.
PIN_HOT_PAIRS = 8
# Rotate the watch window so the rest of the universe is visited during
# a 1-hour run. 90s * 40 pairs ≈ 1600 pair-looks/hour.
WATCH_ROTATE_S = 90
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
    near_miss: NearMiss | None = None


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
    watching: int = 0
    bankroll: Decimal = Decimal("500")
    daily_pnl: Decimal = Decimal("0")
    fills: int = 0
    completed_pairs: int = 0
    naked_incidents: int = 0
    alerts: int = 0
    best_edge: Decimal | None = None
    closest_condition_id: str | None = None
    closest_fillable: Decimal | None = None
    closest_book_age_ms: int | None = None
    closest_in_watch: bool | None = None
    closest_thin: bool | None = None
    nearmiss_considers: int = 0
    edge_histogram: dict[str, int] = field(default_factory=dict)


class StreamHeartbeat:
    """Last stream/poll *receive* time. Distinct from CLOB Book.ts_ms.

    A successful REST liveness probe counts as a receive. Quiet books do not
    mean the socket is dead; a failed probe or dead subscribe does.
    """

    _NEVER_RECEIVED_AGE_MS = 10**15

    def __init__(self) -> None:
        self.last_receive_ms: int | None = None

    def mark(self, now_ms: int) -> None:
        self.last_receive_ms = now_ms

    def age_ms(self, now_ms: int) -> int:
        if self.last_receive_ms is None:
            return self._NEVER_RECEIVED_AGE_MS
        return max(0, now_ms - self.last_receive_ms)


def stream_liveness_probe_due(*, age_ms: int, ws_stale_ms: int) -> bool:
    """True when subscribe silence is approaching ws_stale_ms.

    Do not raise ws_stale_ms. Probe REST first; trip only if that poll fails.
    """
    if ws_stale_ms <= 0:
        return False
    return age_ms >= max(1, (ws_stale_ms * 2) // 3)


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
    *,
    in_watch: bool = False,
    condition_id: str | None = None,
) -> PipelineTrace:
    min_size = (
        yes.min_order_size
        if yes.min_order_size >= no.min_order_size
        else no.min_order_size
    )
    cid = condition_id if condition_id else f"{yes.token_id}:{no.token_id}"
    near = measure_pair(
        yes,
        no,
        min_size,
        _MAX_SHARES,
        now_ms,
        condition_id=cid,
        in_watch=in_watch,
    )
    gap = hunt(yes, no, settings.min_edge, min_size, _MAX_SHARES, now_ms)
    if gap is None:
        return PipelineTrace(None, None, None, None, None, near)
    maker_ev, taker_ev = _estimate_ev(gap, fees)
    reason = _approve_reject_reason(gap, portfolio, settings, market_flags)
    if reason is not None:
        return PipelineTrace(gap, None, reason, maker_ev, taker_ev, near)
    approved = approve(gap, portfolio, settings, market_flags)
    if approved is None:
        return PipelineTrace(gap, None, "risk_rejected", maker_ev, taker_ev, near)
    intent = choose_intent(approved, fees, settings.min_edge)
    if intent is None:
        return PipelineTrace(approved, None, "fee_ev_nonpositive", maker_ev, taker_ev, near)
    return PipelineTrace(approved, intent, None, maker_ev, taker_ev, near)


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


def _optional_decimal_str(value: object) -> str | None:
    """Serialize an optional SDK decimal. Never stringify None/'' to 'None'."""
    if value is None or value == "":
        return None
    return str(value)


def orderbook_to_payload(book: Any, *, now_ms: int) -> dict[str, Any]:
    ts = getattr(book, "timestamp", None)
    if ts is not None and hasattr(ts, "timestamp"):
        ts_ms = int(ts.timestamp() * 1000)
    else:
        ts_ms = int(getattr(book, "ts_ms", now_ms) or now_ms)
    tick = getattr(book, "tick_size", None)
    if tick is None or tick == "":
        tick = getattr(book, "tick", None)
    min_size = getattr(book, "min_order_size", None)
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
        "tick": _optional_decimal_str(tick),
        "min_order_size": _optional_decimal_str(min_size),
        "ts_ms": ts_ms,
        "hash": getattr(book, "hash", None),
    }


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _bump(stats: PaperRunStats, reason: str) -> None:
    stats.rejects[reason] = stats.rejects.get(reason, 0) + 1


def write_paper_stats(
    path: Path,
    stats: PaperRunStats,
    *,
    now_ms: int | None = None,
) -> None:
    """Atomic snapshot for the read-only paper UI. No account data."""
    payload = {
        "markets_listed": stats.markets_listed,
        "universe": stats.universe,
        "gaps": stats.gaps,
        "intents": stats.intents,
        "rejects": sum(stats.rejects.values()),
        "reject_reasons": dict(stats.rejects),
        "watching": stats.watching,
        "bankroll": str(stats.bankroll),
        "daily_pnl": str(stats.daily_pnl),
        "fills": stats.fills,
        "completed_pairs": stats.completed_pairs,
        "naked_incidents": stats.naked_incidents,
        "alerts": stats.alerts,
        "best_edge": str(stats.best_edge) if stats.best_edge is not None else None,
        "closest_condition_id": stats.closest_condition_id,
        "closest_fillable": (
            str(stats.closest_fillable) if stats.closest_fillable is not None else None
        ),
        "closest_book_age_ms": stats.closest_book_age_ms,
        "closest_in_watch": stats.closest_in_watch,
        "closest_thin": stats.closest_thin,
        "nearmiss_considers": stats.nearmiss_considers,
        "edge_histogram": dict(stats.edge_histogram),
        "heartbeat_ms": _now_ms() if now_ms is None else now_ms,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    tmp.replace(path)


def listing_limit(max_markets: int) -> int:
    """How many listed markets to keep. 0 or less means no user cap.

    The safety ceiling always applies so a runaway paginator cannot load
    unbounded catalogs into memory.
    """
    if max_markets <= 0:
        return LIST_SAFETY_CAP
    return min(int(max_markets), LIST_SAFETY_CAP)


def chunk_ids(token_ids: Sequence[str], batch_size: int) -> list[list[str]]:
    """Split token ids into REST get_order_books batches. Never one fat list."""
    size = max(1, int(batch_size))
    ids = list(token_ids)
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def watch_slice(items: Sequence[Any], offset: int, watch_pairs: int) -> list[Any]:
    """Current rotating window. Wraps. Empty if there is nothing to watch."""
    if not items or watch_pairs <= 0:
        return []
    count = min(int(watch_pairs), len(items))
    start = int(offset) % len(items)
    return [items[(start + i) % len(items)] for i in range(count)]


def pair_token_ids(pairs: Sequence[UniversePair]) -> list[str]:
    """YES then NO for each pair so a batch keeps both legs together when even."""
    return [token for pair in pairs for token in (pair.yes_token_id, pair.no_token_id)]


async def _iter_listed_markets(client: Any, max_markets: int) -> list[Any]:
    """Walk official list_markets pages until exhausted, the user cap, or the safety ceiling.

    `page_size` is always LIST_PAGE_SIZE. Do not request one page of
    `page_size=max_markets`.
    """
    limit = listing_limit(max_markets)
    try:
        listed = client.list_markets(closed=False, page_size=LIST_PAGE_SIZE)
        if inspect.isawaitable(listed):
            listed = await listed
    except PublicApiError:
        raise
    except Exception as exc:
        raise PublicApiError(f"public API is unreachable: {exc}") from exc

    items: list[Any] = []

    def _take(market: Any) -> bool:
        items.append(market)
        return len(items) >= limit

    if callable(getattr(listed, "__aiter__", None)):
        async for page in listed:
            page_items = getattr(page, "items", None)
            if page_items is None:
                if _take(page):
                    return items
                continue
            if not page_items:
                break
            for market in page_items:
                if _take(market):
                    return items
        return items

    iter_items = getattr(listed, "iter_items", None)
    if callable(iter_items):
        async for market in iter_items():
            if _take(market):
                break
        return items
    if isinstance(listed, list):
        return listed[:limit]
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


async def fetch_book_batches(
    client: Any,
    token_ids: Sequence[str],
    *,
    batch_size: int = BOOK_BATCH_SIZE,
    on_ok: Any = None,
    on_fail: Any = None,
    raise_if_all_fail: bool = True,
) -> tuple[int, int]:
    """Fetch books in small REST batches. Apply each batch. One fat payload must not kill the run.

    Failed batch: call on_fail and continue. PublicApiError only when every
    batch fails (and raise_if_all_fail). Empty token_ids is a no-op.
    """
    batches = chunk_ids(token_ids, batch_size)
    if not batches:
        return 0, 0
    ok = 0
    failed = 0
    last_exc: BaseException | None = None
    for batch in batches:
        try:
            books = await _fetch_books(client, batch)
        except PublicApiError as exc:
            failed += 1
            last_exc = exc
            if on_fail is not None:
                result = on_fail(batch, exc)
                if inspect.isawaitable(result):
                    await result
            continue
        ok += 1
        if on_ok is not None:
            result = on_ok(books, batch)
            if inspect.isawaitable(result):
                await result
    if ok == 0 and raise_if_all_fail:
        detail = str(last_exc) if last_exc is not None else "every book batch failed"
        raise PublicApiError(
            f"public API is unreachable: every book batch failed ({detail})"
        ) from last_exc
    return ok, failed


async def _updates(
    client: Any,
    token_ids: Sequence[str],
    poll_s: float,
    *,
    batch_size: int = BOOK_BATCH_SIZE,
    on_batch_fail: Any = None,
) -> AsyncIterator[Any]:
    subscribe = getattr(client, "subscribe", None)
    if callable(subscribe):
        try:
            stream = subscribe(list(token_ids))
            if inspect.isawaitable(stream):
                stream = await stream
            async for event in stream:
                yield event
        except asyncio.CancelledError:
            raise
        except PublicApiError:
            raise
        except Exception as exc:
            raise PublicApiError(f"public API is unreachable: {exc}") from exc
        return
    while True:
        ok = 0
        last_exc: BaseException | None = None
        for batch in chunk_ids(token_ids, batch_size):
            try:
                yield await _fetch_books(client, batch)
                ok += 1
            except PublicApiError as exc:
                last_exc = exc
                if on_batch_fail is not None:
                    result = on_batch_fail(batch, exc)
                    if inspect.isawaitable(result):
                        await result
        if ok == 0:
            detail = str(last_exc) if last_exc is not None else "every book batch failed"
            raise PublicApiError(
                f"public API is unreachable: every book batch failed ({detail})"
            ) from last_exc
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


def _sync_tracker_stats(stats: PaperRunStats, tracker: NearMissTracker) -> None:
    snap = tracker.snapshot()
    raw_best = snap["best_edge"]
    stats.best_edge = Decimal(str(raw_best)) if raw_best is not None else None
    stats.closest_condition_id = (
        str(snap["closest_condition_id"]) if snap["closest_condition_id"] else None
    )
    fillable = snap["closest_fillable"]
    stats.closest_fillable = Decimal(str(fillable)) if fillable is not None else None
    age = snap["closest_book_age_ms"]
    stats.closest_book_age_ms = int(age) if age is not None else None
    watch_flag = snap["closest_in_watch"]
    stats.closest_in_watch = bool(watch_flag) if watch_flag is not None else None
    thin_flag = snap["closest_thin"]
    stats.closest_thin = bool(thin_flag) if thin_flag is not None else None
    stats.nearmiss_considers = int(snap["nearmiss_considers"])
    hist = snap["edge_histogram"]
    stats.edge_histogram = dict(hist) if isinstance(hist, dict) else {}


def _nearmiss_row(miss: NearMiss, now_ms: int) -> dict[str, Any]:
    return {
        "ts_ms": now_ms,
        "condition_id": miss.condition_id,
        "raw_edge": str(miss.raw_edge) if miss.raw_edge is not None else None,
        "yes_vwap": str(miss.yes_vwap) if miss.yes_vwap is not None else None,
        "no_vwap": str(miss.no_vwap) if miss.no_vwap is not None else None,
        "fillable_shares": str(miss.fillable_shares),
        "book_age_ms": miss.book_age_ms,
        "in_watch": miss.in_watch,
        "thin": miss.thin,
    }


def _fill_row(fill: PaperFillResult, now_ms: int) -> dict[str, Any]:
    return {
        "ts_ms": now_ms,
        "condition_id": fill.condition_id,
        "path": fill.path,
        "size": str(fill.size),
        "yes_vwap": str(fill.yes_vwap),
        "no_vwap": str(fill.no_vwap),
        "pair_fees": str(fill.pair_fees),
        "cost": str(fill.cost),
        "pnl": str(fill.pnl),
        "bankroll": str(fill.bankroll),
        "daily_pnl": str(fill.daily_pnl),
        "outcome": fill.outcome,
        "naked": fill.naked,
        "hedge_pnl": str(fill.hedge_pnl),
        "completed": fill.completed,
    }


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
    book_batch_size: int = BOOK_BATCH_SIZE,
    watch_pairs: int = WATCH_PAIRS,
    watch_rotate_s: float = WATCH_ROTATE_S,
    honest: bool = True,
    p_miss: Decimal = Decimal("0.3"),
    rng_seed: int = 0,
    record_books: bool = False,
) -> PaperRunStats:
    """Hunt → risk → fee → paper executor. Never places live orders."""
    if settings.arb_mode == "live":
        raise RuntimeError("paper_run is paper-only and will not place live orders")

    gaps_path = data_dir / "gaps.jsonl"
    intents_path = data_dir / "intents.jsonl"
    rejects_path = data_dir / "rejects.jsonl"
    fills_path = data_dir / "fills.jsonl"
    nearmiss_path = data_dir / "nearmiss.jsonl"
    alerts_path = data_dir / "alerts.jsonl"
    stats_path = data_dir / "stats.json"
    stats = PaperRunStats()
    store = BookStore()
    heartbeat = StreamHeartbeat()
    broker = PaperBroker(log_path=intents_path)
    state = StateStore(data_dir / "state.sqlite")
    kill = KillSwitch(
        project_root=project_root,
        state=state,
        settings=settings,
    )
    restored = state.restore()
    starting_bankroll = (
        restored.bankroll
        if restored.bankroll is not None
        else settings.paper_bankroll
    )
    if restored.bankroll is None:
        state.set_bankroll(starting_bankroll)
    ledger = PaperLedger(
        state,
        bankroll=starting_bankroll,
        daily_pnl=restored.daily_pnl,
        honest=honest,
        p_miss=p_miss,
        rng_seed=rng_seed,
        maker_rest_ms=settings.hedge_timeout_ms if honest else 400,
    )
    recorder = BookRecorder(data_dir / "books.jsonl") if record_books else None
    tracker = NearMissTracker()
    watch_scores: dict[str, Decimal] = {}
    stats.bankroll = ledger.bankroll
    stats.daily_pnl = ledger.daily_pnl
    stats.fills = len(restored.fills) // 2
    portfolio = Portfolio(
        yes={}, no={}, open_pairs=0, daily_pnl=ledger.daily_pnl, halted=False
    )
    write_pid(data_dir)

    try:
        markets = await _iter_listed_markets(client, max_markets)
    except BaseException:
        if recorder is not None:
            recorder.close()
        clear_pid(data_dir)
        raise
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
    batch_size = max(1, int(book_batch_size))
    watch_n = max(1, int(watch_pairs))
    rotate_s = float(watch_rotate_s)
    stats.watching = min(len(pairs), watch_n)
    watch_offset = 0
    write_paper_stats(stats_path, stats)

    def current_watch_pairs() -> list[UniversePair]:
        return hot_watch_slice(
            pairs,
            watch_offset,
            watch_n,
            watch_scores,
            pin_n=PIN_HOT_PAIRS,
            condition_id_of=lambda item: item.condition_id,
            rotate_slice=watch_slice,
        )

    def current_watch_tokens() -> list[str]:
        return pair_token_ids(current_watch_pairs())

    def watch_ids() -> set[str]:
        return {item.condition_id for item in current_watch_pairs()}

    def record_pair_books(pair: UniversePair) -> None:
        if recorder is None:
            return
        yes_book = store.get(pair.yes_token_id)
        no_book = store.get(pair.no_token_id)
        if yes_book is not None:
            recorder.write(book_to_event(yes_book, "YES", pair.condition_id))
        if no_book is not None:
            recorder.write(book_to_event(no_book, "NO", pair.condition_id))

    def note_score(miss: NearMiss) -> None:
        if miss.raw_edge is None:
            return
        prev = watch_scores.get(miss.condition_id)
        if prev is None or miss.raw_edge > prev:
            watch_scores[miss.condition_id] = miss.raw_edge

    def apply_settled_fill(fill: PaperFillResult, now_ms: int) -> None:
        if fill.outcome in {"resting", "canceled", "rejected"}:
            return
        stats.fills += 1
        if fill.completed:
            stats.completed_pairs += 1
        if fill.naked:
            stats.naked_incidents += 1
        stats.bankroll = fill.bankroll
        stats.daily_pnl = fill.daily_pnl
        portfolio.daily_pnl = fill.daily_pnl
        _append_jsonl(fills_path, _fill_row(fill, now_ms))

    async def expire_rests(*, force_timeout: bool) -> None:
        now_ms = _now_ms()
        if force_timeout:
            now_ms = now_ms + max(ledger.maker_rest_ms, settings.hedge_timeout_ms)
        for fill in await ledger.poll_rests(store, now_ms):
            apply_settled_fill(fill, _now_ms())
        stats.bankroll = ledger.bankroll
        stats.daily_pnl = ledger.daily_pnl
        write_paper_stats(stats_path, stats)

    async def consider(pair: UniversePair) -> None:
        if read_control(data_dir).paused:
            write_paper_stats(stats_path, stats)
            return
        yes = store.get(pair.yes_token_id)
        no = store.get(pair.no_token_id)
        if yes is None or no is None:
            return
        now_ms = _now_ms()
        in_watch = pair.condition_id in watch_ids()
        portfolio.halted = not kill.allow_new_intents()
        kill.evaluate(
            daily_pnl=portfolio.daily_pnl,
            ws_age_ms=heartbeat.age_ms(now_ms),
            now_ms=now_ms,
        )
        portfolio.halted = not kill.allow_new_intents()
        trace = run_pipeline_traced(
            yes,
            no,
            settings,
            pair.flags,
            pair.fees,
            portfolio,
            now_ms,
            in_watch=in_watch,
            condition_id=pair.condition_id,
        )
        if trace.near_miss is not None:
            miss = trace.near_miss
            note_score(miss)
            if tracker.observe(miss):
                _append_jsonl(nearmiss_path, _nearmiss_row(miss, now_ms))
            _sync_tracker_stats(stats, tracker)
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
            fill = await ledger.try_fill(
                trace.intent, pair.fees, now_ms, mode="paper", yes=yes, no=no
            )
            if fill.outcome == "rejected":
                _append_jsonl(
                    rejects_path,
                    {
                        "ts_ms": now_ms,
                        "condition_id": pair.condition_id,
                        "reason": fill.reject_reason,
                    },
                )
                _bump(stats, fill.reject_reason or "insufficient_bankroll")
            else:
                await paper_execute(trace.intent, broker)
                stats.intents += 1
                stats.alerts += 1
                _append_jsonl(
                    alerts_path,
                    alert_record(trace.intent, now_ms, outcome=fill.outcome),
                )
                apply_settled_fill(fill, now_ms)
        for settled in await ledger.poll_rests(store, now_ms):
            apply_settled_fill(settled, now_ms)
        stats.bankroll = ledger.bankroll
        stats.daily_pnl = ledger.daily_pnl
        _sync_tracker_stats(stats, tracker)
        write_paper_stats(stats_path, stats)

    all_token_ids = pair_token_ids(pairs)

    async def log_batch_fail(batch: list[str], exc: BaseException) -> None:
        now_ms = _now_ms()
        _append_jsonl(
            rejects_path,
            {
                "ts_ms": now_ms,
                "reason": "book_batch_failed",
                "token_ids": list(batch),
                "detail": f"{exc}"[:200],
            },
        )
        _bump(stats, "book_batch_failed")
        write_paper_stats(stats_path, stats)

    async def apply_book_batch(books: Any, _batch: list[str]) -> None:
        now_ms = _now_ms()
        heartbeat.mark(now_ms)
        try:
            _apply_update(store, books, now_ms)
        except InvalidOperation as exc:
            payload = books[0] if isinstance(books, (list, tuple)) and books else books
            token = str(getattr(payload, "token_id", "") or "")
            _append_jsonl(
                rejects_path,
                {
                    "ts_ms": now_ms,
                    "token_id": token,
                    "reason": "invalid_book_update",
                    "detail": f"{type(exc).__name__}: {exc}"[:200],
                },
            )
            _bump(stats, "invalid_book_update")
            write_paper_stats(stats_path, stats)
            return
        for pair in pairs:
            if pair.condition_id in watch_ids():
                record_pair_books(pair)
            await consider(pair)
        stats.watching = len(current_watch_pairs())
        write_paper_stats(stats_path, stats)

    if all_token_ids:
        try:
            await fetch_book_batches(
                client,
                all_token_ids,
                batch_size=batch_size,
                on_ok=apply_book_batch,
                on_fail=log_batch_fail,
                raise_if_all_fail=True,
            )
        except BaseException:
            if recorder is not None:
                recorder.close()
            clear_pid(data_dir)
            raise

    if once or not all_token_ids:
        await expire_rests(force_timeout=True)
        _sync_tracker_stats(stats, tracker)
        write_paper_stats(stats_path, stats)
        if recorder is not None:
            recorder.close()
        clear_pid(data_dir)
        return stats

    deadline = time.monotonic() + seconds
    rotated = asyncio.Event()

    stats.watching = len(current_watch_pairs())
    write_paper_stats(stats_path, stats)

    def trip_dead_stream() -> None:
        """Persist ws_stale. Never auto-resumes."""
        now_ms = _now_ms()
        kill.evaluate(
            daily_pnl=portfolio.daily_pnl,
            ws_age_ms=settings.ws_stale_ms + 1,
            now_ms=now_ms,
        )
        portfolio.halted = not kill.allow_new_intents()

    async def handle_update(update: Any) -> None:
        now_ms = _now_ms()
        heartbeat.mark(now_ms)
        try:
            _apply_update(store, update, now_ms)
        except InvalidOperation as exc:
            payload = getattr(update, "payload", update)
            token = str(getattr(payload, "token_id", "") or "")
            _append_jsonl(
                rejects_path,
                {
                    "ts_ms": now_ms,
                    "token_id": token,
                    "reason": "invalid_book_update",
                    "detail": f"{type(exc).__name__}: {exc}"[:200],
                },
            )
            _bump(stats, "invalid_book_update")
            write_paper_stats(stats_path, stats)
            return
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
            if pair.condition_id in watch_ids():
                record_pair_books(pair)
            await consider(pair)

    async def consume_slice() -> None:
        tokens = current_watch_tokens()
        try:
            async for update in _updates(
                client,
                tokens,
                poll_s,
                batch_size=batch_size,
                on_batch_fail=log_batch_fail,
            ):
                await handle_update(update)
                if time.monotonic() >= deadline:
                    return
        except asyncio.CancelledError:
            raise
        except PublicApiError:
            trip_dead_stream()
            return
        if time.monotonic() < deadline:
            trip_dead_stream()

    async def consume() -> None:
        while time.monotonic() < deadline:
            rotated.clear()
            slice_task = asyncio.create_task(consume_slice())
            rotate_wait = asyncio.create_task(rotated.wait())
            remaining = deadline - time.monotonic()
            done, pending = await asyncio.wait(
                {slice_task, rotate_wait},
                timeout=max(0.0, remaining),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if slice_task in done and not slice_task.cancelled():
                return
            if not done:
                return

    async def rotate_watch() -> None:
        nonlocal watch_offset
        if len(pairs) <= watch_n:
            return
        while True:
            if read_control(data_dir).paused:
                write_paper_stats(stats_path, stats)
                await asyncio.sleep(min(0.25, poll_s if poll_s > 0 else 0.25))
                continue
            target = effective_rotate_s(data_dir, rotate_s)
            if target <= 0:
                return
            waited = 0.0
            while waited < target:
                if read_control(data_dir).paused:
                    break
                target = effective_rotate_s(data_dir, rotate_s)
                if target <= 0:
                    return
                step_s = min(0.25, max(0.0, target - waited))
                if step_s <= 0:
                    break
                await asyncio.sleep(step_s)
                waited += step_s
            if read_control(data_dir).paused:
                continue
            if effective_rotate_s(data_dir, rotate_s) <= 0:
                return
            pinned_n = min(PIN_HOT_PAIRS, watch_n, len(pairs))
            if len(pairs) > watch_n:
                pinned_n = min(pinned_n, max(0, watch_n - 1))
            rest_n = max(1, len(pairs) - pinned_n)
            rotate_n = max(1, watch_n - pinned_n)
            watch_offset = (watch_offset + rotate_n) % rest_n
            next_tokens = current_watch_tokens()
            await fetch_book_batches(
                client,
                next_tokens,
                batch_size=batch_size,
                on_ok=apply_book_batch,
                on_fail=log_batch_fail,
                raise_if_all_fail=False,
            )
            stats.watching = len(current_watch_pairs())
            write_paper_stats(stats_path, stats)
            rotated.set()

    async def watch_silence() -> None:
        interval_s = max(0.02, min(poll_s, settings.ws_stale_ms / 1000))
        probe_timeout_s = max(0.05, settings.ws_stale_ms / 1000)
        while True:
            await asyncio.sleep(interval_s)
            now_ms = _now_ms()
            if not kill.allow_new_intents():
                kill.evaluate(
                    daily_pnl=portfolio.daily_pnl,
                    ws_age_ms=heartbeat.age_ms(now_ms),
                    now_ms=now_ms,
                )
                continue
            age = heartbeat.age_ms(now_ms)
            if stream_liveness_probe_due(
                age_ms=age, ws_stale_ms=settings.ws_stale_ms
            ):
                probe_ok = 0

                async def probe_ok_batch(books: Any, _batch: list[str]) -> None:
                    nonlocal probe_ok
                    probe_ok += 1
                    await handle_update(books)

                async def probe_one(batch: list[str]) -> None:
                    try:
                        books = await asyncio.wait_for(
                            _fetch_books(client, batch),
                            timeout=probe_timeout_s,
                        )
                    except (PublicApiError, TimeoutError, asyncio.TimeoutError) as exc:
                        await log_batch_fail(batch, exc)
                        return
                    await probe_ok_batch(books, batch)

                for batch in chunk_ids(current_watch_tokens(), batch_size):
                    await probe_one(batch)
                    write_paper_stats(stats_path, stats)
                if probe_ok == 0:
                    trip_dead_stream()
                continue
            kill.evaluate(
                daily_pnl=portfolio.daily_pnl,
                ws_age_ms=age,
                now_ms=now_ms,
            )

    watch = asyncio.create_task(watch_silence())
    rotator = asyncio.create_task(rotate_watch())
    try:
        remaining = deadline - time.monotonic()
        finished_on_timeout = False
        if remaining > 0:
            try:
                await asyncio.wait_for(consume(), timeout=remaining)
            except asyncio.TimeoutError:
                finished_on_timeout = True
        now_ms = _now_ms()
        # Planned window end is not a dead socket. watch_silence already
        # probed; do not race an in-flight REST poll into a false ws_stale.
        kill.evaluate(
            daily_pnl=portfolio.daily_pnl,
            ws_age_ms=0 if finished_on_timeout else heartbeat.age_ms(now_ms),
            now_ms=now_ms,
        )
    finally:
        rotator.cancel()
        watch.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await rotator
        with contextlib.suppress(asyncio.CancelledError):
            await watch
        await expire_rests(force_timeout=True)
        if recorder is not None:
            recorder.close()
        clear_pid(data_dir)
    _sync_tracker_stats(stats, tracker)
    write_paper_stats(stats_path, stats)
    return stats
