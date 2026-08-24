"""WS MarketBookPayload mapping. Official SDK types only. No network."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

import pytest
from polymarket.models.clob.market_events import MarketBookEvent, parse_market_event
from polymarket.models.clob.order_book import OrderBook

from arb.app import _apply_update, orderbook_to_payload
from arb.books import BookStore, Level
from arb.money import d

_TOKEN = "yes-gap-3c"
_MARKET = "0x" + ("ab" * 32)
_NOW_MS = 1_724_496_123_000


def _ws_event(*, min_order_size: object = "", tick_size: object = "") -> MarketBookEvent:
    event = parse_market_event(
        {
            "event_type": "book",
            "market": _MARKET,
            "asset_id": _TOKEN,
            "bids": [{"price": "0.54", "size": "10"}],
            "asks": [{"price": "0.55", "size": "80"}],
            "timestamp": str(_NOW_MS),
            "hash": "ws-book-hash-v1",
            "min_order_size": min_order_size,
            "tick_size": tick_size,
        }
    )
    assert isinstance(event, MarketBookEvent)
    return event


def test_ws_empty_min_order_size_does_not_stringify_none() -> None:
    event = _ws_event(min_order_size="", tick_size="")
    assert event.payload.min_order_size is None
    assert event.payload.tick_size is None
    mapped = orderbook_to_payload(event.payload, now_ms=_NOW_MS)
    assert mapped["min_order_size"] is None
    assert mapped["tick"] is None
    with pytest.raises(InvalidOperation):
        d("None")


def test_ws_book_without_min_order_size_applies_default() -> None:
    store = BookStore()
    _apply_update(store, _ws_event(min_order_size="", tick_size=""), now_ms=_NOW_MS)
    book = store.get(_TOKEN)
    assert book is not None
    assert book.min_order_size == Decimal("5")
    assert book.tick == Decimal("0.01")
    assert book.asks[0].price == Decimal("0.55")


def test_ws_book_keeps_previous_rest_min_order_size() -> None:
    rest = OrderBook.parse_response(
        {
            "market": _MARKET,
            "asset_id": _TOKEN,
            "bids": [{"price": "0.54", "size": "10"}],
            "asks": [{"price": "0.55", "size": "80"}],
            "timestamp": str(_NOW_MS),
            "hash": "rest-book-hash-v1",
            "tick_size": "0.01",
            "min_order_size": "1",
            "neg_risk": False,
        }
    )
    store = BookStore()
    _apply_update(store, [rest], now_ms=_NOW_MS)
    assert store.get(_TOKEN) is not None
    assert store.get(_TOKEN).min_order_size == Decimal("1")
    _apply_update(store, _ws_event(min_order_size="", tick_size=""), now_ms=_NOW_MS)
    book = store.get(_TOKEN)
    assert book is not None
    assert book.min_order_size == Decimal("1")
    assert book.tick == Decimal("0.01")


def test_apply_snapshot_float_price_still_raises() -> None:
    store = BookStore()
    with pytest.raises(TypeError, match="must be Decimal, not float"):
        store.apply_snapshot(
            {
                "token_id": _TOKEN,
                "bids": [],
                "asks": [{"price": 0.55, "size": "80"}],
                "tick": "0.01",
                "min_order_size": "5",
                "ts_ms": _NOW_MS,
            }
        )
    assert store.get(_TOKEN) is None


def test_level_float_still_raises() -> None:
    with pytest.raises(TypeError, match="must be Decimal, not float"):
        Level(price=0.55, size=80)  # type: ignore[arg-type]


def test_empty_ask_price_still_raises_on_direct_snapshot() -> None:
    store = BookStore()
    with pytest.raises(InvalidOperation):
        store.apply_snapshot(
            {
                "token_id": _TOKEN,
                "bids": [],
                "asks": [{"price": "", "size": "80"}],
                "tick": "0.01",
                "min_order_size": "5",
                "ts_ms": _NOW_MS,
            }
        )
    assert store.get(_TOKEN) is None


def test_mapper_none_attr_is_not_the_string_none() -> None:
    book = SimpleNamespace(
        token_id=_TOKEN,
        bids=(SimpleNamespace(price=d("0.54"), size=d("10")),),
        asks=(SimpleNamespace(price=d("0.55"), size=d("80")),),
        tick_size=None,
        min_order_size=None,
        timestamp=None,
        ts_ms=_NOW_MS,
        hash="none-attr",
    )
    mapped = orderbook_to_payload(book, now_ms=_NOW_MS)
    assert mapped["min_order_size"] is None
    assert mapped["tick"] is None
    stored = BookStore().apply_snapshot(mapped)
    assert stored.min_order_size == Decimal("5")
    assert stored.tick == Decimal("0.01")
