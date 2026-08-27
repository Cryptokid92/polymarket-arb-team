"""Public book recorder. Official client only. No live orders."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from arb.app import PublicApiError
from arb.money import d
from arb.recorder import book_to_event, frames_from_events, load_jsonl
from arb.books import Book, Level


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "record_books_cli", Path("scripts/record_books.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _market(yes_id: str = "yes-gap-3c", no_id: str = "no-gap-3c") -> SimpleNamespace:
    return SimpleNamespace(
        condition_id="0xcond",
        slug="will-x-happen",
        question="Will X happen?",
        category="Politics",
        group_item_title="",
        tags=(),
        state=SimpleNamespace(
            accepting_orders=True, neg_risk=False, closed=False, archived=False
        ),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id=yes_id, label="Yes", price=None),
            no=SimpleNamespace(token_id=no_id, label="No", price=None),
        ),
        trading=SimpleNamespace(seconds_delay=0, fee_schedule=None),
    )


def _book(token_id: str, bid: str, ask: str) -> SimpleNamespace:
    return SimpleNamespace(
        token_id=token_id,
        bids=(SimpleNamespace(price=d(bid), size=d("20")),),
        asks=(SimpleNamespace(price=d(ask), size=d("80")),),
        tick_size=d("0.01"),
        min_order_size=d("5"),
        timestamp=None,
        ts_ms=1000,
        hash="fixture",
    )


class _MockPublic:
    def __init__(self, markets: list[object], books: dict[str, object]) -> None:
        self.markets = markets
        self.books = books

    def list_markets(self, *, closed: bool = False, page_size: int = 100, **kwargs):
        async def gen():
            for item in self.markets:
                yield item

        return SimpleNamespace(iter_items=lambda: gen())

    async def get_order_books(self, *, token_ids: list[str]):
        return [self.books[token] for token in token_ids if token in self.books]


def test_record_books_cli_refuses_place_orders() -> None:
    module = _load_script()
    assert module.main(["--place-orders"]) == 2
    source = Path("scripts/record_books.py").read_text(encoding="utf-8")
    assert "AsyncSecureClient" not in source
    assert "AsyncPublicClient" in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "AsyncSecureClient"


def test_frames_do_not_mix_yes_and_no_across_markets() -> None:
    yes_a = Book(
        token_id="yes-a",
        bids=[Level(price=d("0.10"), size=d("80"))],
        asks=[Level(price=d("0.11"), size=d("80"))],
        tick=d("0.01"),
        min_order_size=d("5"),
        ts_ms=1000,
    )
    no_b = Book(
        token_id="no-b",
        bids=[Level(price=d("0.10"), size=d("80"))],
        asks=[Level(price=d("0.11"), size=d("80"))],
        tick=d("0.01"),
        min_order_size=d("5"),
        ts_ms=1000,
    )
    events = [
        book_to_event(yes_a, "YES", "market-a"),
        book_to_event(no_b, "NO", "market-b"),
    ]
    assert frames_from_events(events) == []


def test_book_to_event_round_trips_frames() -> None:
    yes = Book(
        token_id="yes-1",
        bids=[Level(price=d("0.54"), size=d("10"))],
        asks=[Level(price=d("0.55"), size=d("80"))],
        tick=d("0.01"),
        min_order_size=d("5"),
        ts_ms=1000,
    )
    no = Book(
        token_id="no-1",
        bids=[Level(price=d("0.41"), size=d("10"))],
        asks=[Level(price=d("0.42"), size=d("80"))],
        tick=d("0.01"),
        min_order_size=d("5"),
        ts_ms=1000,
    )
    events = [
        book_to_event(yes, "YES", "c1"),
        book_to_event(no, "NO", "c1"),
    ]
    frames = frames_from_events(events)
    assert len(frames) == 1
    assert frames[0].yes.token_id == "yes-1"
    assert frames[0].no.asks[0].price == d("0.42")


@pytest.mark.asyncio
async def test_record_public_books_writes_watch_slice(tmp_path: Path) -> None:
    module = _load_script()
    client = _MockPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
        },
    )
    out = tmp_path / "books.jsonl"
    written = await module.record_public_books(
        client,
        out=out,
        max_markets=20,
        once=True,
        seconds=1,
        book_batch_size=50,
        watch_pairs=40,
    )
    assert written >= 2
    events = load_jsonl(out)
    assert events[0]["market_side"] in {"YES", "NO"}
    assert frames_from_events(events)


@pytest.mark.asyncio
async def test_record_public_books_errors_when_universe_empty(tmp_path: Path) -> None:
    module = _load_script()
    client = _MockPublic([], {})
    with pytest.raises(PublicApiError):
        await module.record_public_books(
            client,
            out=tmp_path / "books.jsonl",
            max_markets=20,
            once=True,
            seconds=1,
            book_batch_size=50,
            watch_pairs=40,
        )
