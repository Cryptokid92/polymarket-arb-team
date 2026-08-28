"""Maker completeness quotes. Hunt stays silent on asks. Caps stay tight."""

from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from typing import get_args, get_origin, get_type_hints

from arb.app import (
    BOOK_BATCH_SIZE,
    LIST_SAFETY_CAP,
    PIN_HOT_PAIRS,
    WATCH_PAIRS,
    run_pipeline_traced,
)
from arb.books import Book, Level
from arb.config import Settings, _EnvSettings
from arb.fee_agent import MarketFees
from arb.hunter import hunt
from arb.maker import gap_from_maker_quotes, maker_complete_quotes
from arb.money import d
from arb.risk import MarketFlags, Portfolio

MIN_EDGE = d("0.01")
MAX_GAP = d("0.08")
MIN_SIZE = d("5")
MAX_NOTIONAL = d("25")
STALE_MS = 400


def _type_includes_float(annotation: object) -> bool:
    origin = get_origin(annotation)
    if annotation is float:
        return True
    if origin is None:
        return annotation is float
    return any(arg is float for arg in get_args(annotation))


def _book(
    token_id: str,
    bid: str,
    ask: str,
    *,
    bid_size: str = "20",
    ask_size: str = "50",
    ts_ms: int = 1000,
) -> Book:
    return Book(
        token_id=token_id,
        bids=[Level(price=d(bid), size=d(bid_size))],
        asks=[Level(price=d(ask), size=d(ask_size))],
        tick=d("0.01"),
        min_order_size=MIN_SIZE,
        ts_ms=ts_ms,
    )


def _settings() -> Settings:
    return Settings(
        arb_mode="paper",
        max_notional_per_trade=MAX_NOTIONAL,
        max_daily_loss=d("50"),
        max_open_pairs=3,
        min_edge=MIN_EDGE,
        max_gap=MAX_GAP,
        stale_ms=STALE_MS,
        hedge_timeout_ms=1500,
        ws_stale_ms=3000,
    )


def test_join_bids_when_sum_is_a_cent_or_better() -> None:
    yes = _book("yes-flat", "0.49", "0.50")
    no = _book("no-flat", "0.49", "0.50")
    assert hunt(yes, no, MIN_EDGE, MIN_SIZE, d("50"), now_ms=1000) is None
    quotes = maker_complete_quotes(
        yes,
        no,
        min_edge=MIN_EDGE,
        max_gap=MAX_GAP,
        min_size=MIN_SIZE,
        max_notional=MAX_NOTIONAL,
        stale_ms=STALE_MS,
        now_ms=1000,
    )
    assert quotes is not None
    assert quotes.yes_bid == d("0.49")
    assert quotes.no_bid == d("0.49")
    assert quotes.raw_edge == d("0.02")
    assert quotes.size == d("20")
    assert quotes.yes_bid + quotes.no_bid == d("0.98")


def test_refuse_when_bid_sum_is_not_min_edge() -> None:
    yes = _book("yes-tight", "0.50", "0.51")
    no = _book("no-tight", "0.50", "0.51")
    assert (
        maker_complete_quotes(
            yes,
            no,
            min_edge=MIN_EDGE,
            max_gap=MAX_GAP,
            min_size=MIN_SIZE,
            max_notional=MAX_NOTIONAL,
            stale_ms=STALE_MS,
            now_ms=1000,
        )
        is None
    )


def test_refuse_thin_stale_and_too_good() -> None:
    thin = maker_complete_quotes(
        _book("y", "0.49", "0.50", bid_size="2"),
        _book("n", "0.49", "0.50", bid_size="2"),
        min_edge=MIN_EDGE,
        max_gap=MAX_GAP,
        min_size=MIN_SIZE,
        max_notional=MAX_NOTIONAL,
        stale_ms=STALE_MS,
        now_ms=1000,
    )
    assert thin is None
    stale = maker_complete_quotes(
        _book("y", "0.49", "0.50", ts_ms=1000),
        _book("n", "0.49", "0.50", ts_ms=1000),
        min_edge=MIN_EDGE,
        max_gap=MAX_GAP,
        min_size=MIN_SIZE,
        max_notional=MAX_NOTIONAL,
        stale_ms=STALE_MS,
        now_ms=2000,
    )
    assert stale is None
    too_good = maker_complete_quotes(
        _book("y", "0.40", "0.50"),
        _book("n", "0.40", "0.50"),
        min_edge=MIN_EDGE,
        max_gap=MAX_GAP,
        min_size=MIN_SIZE,
        max_notional=MAX_NOTIONAL,
        stale_ms=STALE_MS,
        now_ms=1000,
    )
    assert too_good is None


def test_clips_size_to_max_notional_grid() -> None:
    yes = _book("y", "0.49", "0.50", bid_size="100")
    no = _book("n", "0.49", "0.50", bid_size="100")
    quotes = maker_complete_quotes(
        yes,
        no,
        min_edge=MIN_EDGE,
        max_gap=MAX_GAP,
        min_size=MIN_SIZE,
        max_notional=MAX_NOTIONAL,
        stale_ms=STALE_MS,
        now_ms=1000,
    )
    assert quotes is not None
    assert quotes.size * (quotes.yes_bid + quotes.no_bid) <= MAX_NOTIONAL
    assert quotes.size >= MIN_SIZE
    assert quotes.size % MIN_SIZE == 0


def test_pipeline_maker_path_when_asks_are_complete() -> None:
    yes = _book("yes-flat", "0.49", "0.50")
    no = _book("no-flat", "0.49", "0.50")
    flags = MarketFlags(
        accepting_orders=True, seconds_delay=0, neg_risk=False, binary=True
    )
    portfolio = Portfolio(yes={}, no={}, open_pairs=0, daily_pnl=d("0"), halted=False)
    trace = run_pipeline_traced(
        yes,
        no,
        _settings(),
        flags,
        MarketFees(yes_rate=d("0"), no_rate=d("0")),
        portfolio,
        1000,
        in_watch=True,
        condition_id="c-flat",
        window_id=3,
    )
    assert hunt(yes, no, MIN_EDGE, MIN_SIZE, d("50"), now_ms=1000) is None
    assert trace.source == "maker"
    assert trace.gap is not None
    assert trace.intent is not None
    assert trace.intent.path == "maker_gtc"
    assert trace.gap.raw_edge == d("0.02")
    assert trace.near_miss is not None
    assert trace.near_miss.raw_edge == d("0")
    assert trace.near_miss.window_id == 3


def test_gap_from_quotes_is_walkable_by_risk() -> None:
    yes = _book("y", "0.49", "0.50")
    no = _book("n", "0.49", "0.50")
    quotes = maker_complete_quotes(
        yes,
        no,
        min_edge=MIN_EDGE,
        max_gap=MAX_GAP,
        min_size=MIN_SIZE,
        max_notional=MAX_NOTIONAL,
        stale_ms=STALE_MS,
        now_ms=1000,
    )
    assert quotes is not None
    gap = gap_from_maker_quotes(yes, no, quotes, 1000, "c-flat")
    assert gap.yes_asks[0].price == quotes.yes_bid
    assert gap.no_asks[0].price == quotes.no_bid
    assert gap.fillable_shares == quotes.size


def test_maker_does_not_loosen_caps() -> None:
    fields = _EnvSettings.model_fields
    assert fields["stale_ms"].default == 400
    assert fields["min_edge"].default == Decimal("0.01")
    assert fields["max_gap"].default == Decimal("0.08")
    assert fields["max_notional_per_trade"].default == Decimal("25")
    assert LIST_SAFETY_CAP == 5000
    assert BOOK_BATCH_SIZE == 50
    assert WATCH_PAIRS == 100
    assert PIN_HOT_PAIRS == 8


def test_maker_never_uses_float() -> None:
    for fn in (maker_complete_quotes, gap_from_maker_quotes):
        hints = get_type_hints(fn)
        for name, annotation in hints.items():
            assert not _type_includes_float(annotation), name
        tree = ast.parse(inspect.getsource(fn))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "float"
            if isinstance(node, ast.Constant) and type(node.value) is float:
                raise AssertionError("maker must not use float literals")
    source = inspect.getsource(maker_complete_quotes)
    assert "AsyncSecureClient" not in source
