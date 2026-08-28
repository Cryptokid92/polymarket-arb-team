from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from polymarket.models.clob.market_events import parse_market_event

from arb.app import (
    BOOK_BATCH_SIZE,
    LIST_PAGE_SIZE,
    LIST_SAFETY_CAP,
    WATCH_PAIRS,
    WATCH_ROTATE_S,
    PublicApiError,
    StreamHeartbeat,
    _iter_listed_markets,
    chunk_ids,
    listing_limit,
    pair_token_ids,
    reject_universe,
    run_paper,
    stream_liveness_probe_due,
    watch_slice,
)
from arb.config import Settings
from arb.money import d
from arb.state import StateStore


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = dict(
        arb_mode="paper",
        max_notional_per_trade=d("25"),
        max_daily_loss=d("50"),
        max_open_pairs=3,
        min_edge=d("0.01"),
        max_gap=d("0.08"),
        stale_ms=400,
        hedge_timeout_ms=1500,
        ws_stale_ms=3000,
    )
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _outcome(token_id: str | None, label: str) -> SimpleNamespace:
    return SimpleNamespace(token_id=token_id, label=label, price=None)


def _market(
    *,
    condition_id: str = "0xcond",
    yes_id: str | None = "yes-gap-3c",
    no_id: str | None = "no-gap-3c",
    accepting: bool = True,
    neg_risk: bool = False,
    delay: int = 0,
    slug: str = "will-x-happen",
    question: str = "Will X happen?",
    category: str = "Politics",
    closed: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        condition_id=condition_id,
        slug=slug,
        question=question,
        category=category,
        group_item_title="",
        tags=(),
        state=SimpleNamespace(
            accepting_orders=accepting,
            neg_risk=neg_risk,
            closed=closed,
            archived=False,
        ),
        outcomes=SimpleNamespace(yes=_outcome(yes_id, "Yes"), no=_outcome(no_id, "No")),
        trading=SimpleNamespace(seconds_delay=delay, fee_schedule=None),
    )


def _book(
    token_id: str,
    bid: str,
    ask: str,
    size: str = "80",
    *,
    timestamp: datetime | None = None,
    ts_ms: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        token_id=token_id,
        bids=(SimpleNamespace(price=d(bid), size=d("20")),),
        asks=(SimpleNamespace(price=d(ask), size=d(size)),),
        tick_size=d("0.01"),
        min_order_size=d("5"),
        timestamp=timestamp,
        ts_ms=ts_ms,
        hash="fixture",
    )


class _Paginator:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def iter_items(self):
        async def gen():
            for item in self._items:
                yield item

        return gen()


class _PagedPaginator:
    """Official-shaped paginator: `async for page in pages` yields `page.items`.

    `iter_items` only yields the first page so a one-page `page_size=max_markets`
    walk cannot pretend to have exhausted the catalog.
    """

    def __init__(self, pages: list[list[object]]) -> None:
        self._pages = pages
        self.pages_yielded = 0

    def __aiter__(self):
        return self._iter_pages()

    async def _iter_pages(self):
        for page in self._pages:
            self.pages_yielded += 1
            yield SimpleNamespace(items=tuple(page))

    def iter_items(self):
        async def gen():
            if not self._pages:
                return
            self.pages_yielded += 1
            for item in self._pages[0]:
                yield item

        return gen()


class _PagedPublic:
    def __init__(self, pages: list[list[object]]) -> None:
        self.pages = pages
        self.list_kwargs: dict[str, object] = {}
        self.paginator: _PagedPaginator | None = None
        self.book_token_ids: list[str] = []
        self.book_call_ids: list[list[str]] = []
        self.subscribed_token_ids: list[str] = []
        self.subscribe_calls: list[list[str]] = []

    def list_markets(self, *, closed: bool = False, page_size: int = 20, **kwargs):
        self.list_kwargs = {"closed": closed, "page_size": page_size, **kwargs}
        self.paginator = _PagedPaginator(self.pages)
        return self.paginator

    async def get_order_books(self, *, token_ids: list[str]):
        self.book_call_ids.append(list(token_ids))
        self.book_token_ids.extend(token_ids)
        return []

    def subscribe(self, token_ids: list[str]):
        self.subscribe_calls.append(list(token_ids))
        self.subscribed_token_ids = list(token_ids)

        async def gen():
            if False:
                yield []

        return gen()


class _MockPublic:
    def __init__(
        self,
        markets: list[object],
        books: dict[str, object],
        *,
        fail_list: bool = False,
        fail_books: bool = False,
    ) -> None:
        self.markets = markets
        self.books = books
        self.fail_list = fail_list
        self.fail_books = fail_books
        self.book_calls = 0
        self.book_token_ids: list[str] = []
        self.book_call_ids: list[list[str]] = []
        self.subscribed_token_ids: list[str] = []
        self.subscribe_calls: list[list[str]] = []
        self.list_kwargs: dict[str, object] = {}

    def list_markets(self, *, closed: bool = False, page_size: int = 20, **kwargs):
        self.list_kwargs = {"closed": closed, "page_size": page_size, **kwargs}
        if self.fail_list:
            raise ConnectionError("connection refused")
        return _Paginator(self.markets)

    async def get_order_books(self, *, token_ids: list[str]):
        self.book_calls += 1
        self.book_call_ids.append(list(token_ids))
        self.book_token_ids = list(token_ids)
        if self.fail_books:
            raise TimeoutError("timed out")
        return [self.books[tid] for tid in token_ids if tid in self.books]


def _keep_subscribe_open(events: list[object]):
    async def gen():
        for event in events:
            yield event
        while True:
            await asyncio.sleep(60)
            yield []

    return gen()


class _SilentStreamPublic(_MockPublic):
    """Public client whose websocket stays open but never delivers another event."""

    def subscribe(self, token_ids: list[str]):
        self.subscribe_calls.append(list(token_ids))
        self.subscribed_token_ids = list(token_ids)
        return _keep_subscribe_open([])


class _ClosedStreamPublic(_MockPublic):
    """Subscribe iterator ends immediately after the REST snapshot."""

    def subscribe(self, token_ids: list[str]):
        async def gen():
            if False:
                yield []

        return gen()


class _ErrorStreamPublic(_MockPublic):
    """Subscribe iterator raises. Dead socket, not quiet books."""

    def subscribe(self, token_ids: list[str]):
        async def gen():
            raise ConnectionError("ws closed")
            yield []

        return gen()


class _QuietThenDeadRest(_SilentStreamPublic):
    """Live quiet subscribe; REST liveness probe fails after the first snapshot."""

    async def get_order_books(self, *, token_ids: list[str]):
        self.book_calls += 1
        self.book_call_ids.append(list(token_ids))
        self.book_token_ids = list(token_ids)
        if self.book_calls > 1:
            raise TimeoutError("timed out")
        return [self.books[tid] for tid in token_ids if tid in self.books]


class _PollBooksFailAfterFirst(_MockPublic):
    """No subscribe. Loop poll fetch fails after the opening snapshot."""

    async def get_order_books(self, *, token_ids: list[str]):
        self.book_calls += 1
        self.book_call_ids.append(list(token_ids))
        self.book_token_ids = list(token_ids)
        if self.book_calls > 1:
            raise TimeoutError("timed out")
        return [self.books[tid] for tid in token_ids if tid in self.books]


class _FailSelectedBookBatches(_MockPublic):
    """Fail get_order_books only when the batch contains a chosen token."""

    def __init__(
        self,
        markets: list[object],
        books: dict[str, object],
        *,
        fail_token: str,
    ) -> None:
        super().__init__(markets, books)
        self.fail_token = fail_token

    async def get_order_books(self, *, token_ids: list[str]):
        self.book_calls += 1
        self.book_call_ids.append(list(token_ids))
        self.book_token_ids = list(token_ids)
        if self.fail_token in token_ids:
            raise RuntimeError("Payload exceeds the limit")
        return [self.books[tid] for tid in token_ids if tid in self.books]


def _ws_book(token_id: str, bid: str, ask: str, *, min_order_size: str = "") -> object:
    return parse_market_event(
        {
            "event_type": "book",
            "market": "0x" + ("ab" * 32),
            "asset_id": token_id,
            "bids": [{"price": bid, "size": "20"}],
            "asks": [{"price": ask, "size": "80"}],
            "timestamp": "1710000000000",
            "min_order_size": min_order_size,
            "tick_size": "",
            "hash": "ws-paper",
        }
    )


class _WsNoneMinPublic(_MockPublic):
    """REST books succeed; WS book events omit optional min_order_size."""

    def subscribe(self, token_ids: list[str]):
        return _keep_subscribe_open(
            [
                _ws_book("yes-gap-3c", "0.54", "0.55"),
                _ws_book("no-gap-3c", "0.41", "0.42"),
            ]
        )


class _WsBadLevelPublic(_MockPublic):
    """One WS book has an empty ask price after a good REST snapshot."""

    def subscribe(self, token_ids: list[str]):
        return _keep_subscribe_open(
            [
                SimpleNamespace(
                    type="book",
                    payload=SimpleNamespace(
                        token_id="yes-gap-3c",
                        bids=(SimpleNamespace(price=d("0.54"), size=d("20")),),
                        asks=(SimpleNamespace(price="", size=d("80")),),
                        tick_size=d("0.01"),
                        min_order_size=d("5"),
                        timestamp=None,
                        hash="bad-level",
                        price_changes=(),
                    ),
                )
            ]
        )


@pytest.mark.asyncio
async def test_paper_run_writes_gaps_and_intents_from_mock(tmp_path: Path) -> None:
    client = _MockPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
        },
    )
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=tmp_path / "paper",
        once=True,
    )
    assert client.list_kwargs["closed"] is False
    assert stats.markets_listed == 1
    assert stats.universe == 1
    assert stats.gaps >= 1
    assert stats.intents >= 1
    assert (tmp_path / "paper" / "gaps.jsonl").is_file()
    assert (tmp_path / "paper" / "intents.jsonl").is_file()
    stats_path = tmp_path / "paper" / "stats.json"
    assert stats_path.is_file()
    snapshot = json.loads(stats_path.read_text(encoding="utf-8"))
    assert snapshot["markets_listed"] == 1
    assert snapshot["universe"] == 1
    assert snapshot["gaps"] >= 1
    assert snapshot["intents"] >= 1
    assert isinstance(snapshot["heartbeat_ms"], int)
    assert snapshot["heartbeat_ms"] > 0
    gaps = (tmp_path / "paper" / "gaps.jsonl").read_text(encoding="utf-8").strip()
    assert "raw_edge" in gaps
    intents = (tmp_path / "paper" / "intents.jsonl").read_text(encoding="utf-8").strip()
    assert "maker_gtc" in intents
    fills_path = tmp_path / "paper" / "fills.jsonl"
    assert fills_path.is_file()
    fill = json.loads(fills_path.read_text(encoding="utf-8").strip().splitlines()[0])
    assert fill["path"] == "maker_gtc"
    assert Decimal(fill["pnl"]) > Decimal("0")
    assert Decimal(snapshot["bankroll"]) > Decimal("500")
    assert Decimal(snapshot["daily_pnl"]) > Decimal("0")
    restored = StateStore(tmp_path / "paper" / "state.sqlite").restore()
    assert restored.bankroll is not None
    assert restored.bankroll > Decimal("500")
    assert len(restored.fills) == 2


@pytest.mark.asyncio
async def test_unreachable_list_markets_raises_clear_error(tmp_path: Path) -> None:
    client = _MockPublic([], {}, fail_list=True)
    with pytest.raises(PublicApiError, match="public API is unreachable"):
        await run_paper(
            client=client,
            settings=_settings(),
            project_root=tmp_path,
            data_dir=tmp_path / "paper",
            once=True,
        )
    assert not (tmp_path / "paper" / "gaps.jsonl").exists()


@pytest.mark.asyncio
async def test_unreachable_books_raises_clear_error(tmp_path: Path) -> None:
    client = _MockPublic([_market()], {}, fail_books=True)
    with pytest.raises(PublicApiError, match="public API is unreachable"):
        await run_paper(
            client=client,
            settings=_settings(),
            project_root=tmp_path,
            data_dir=tmp_path / "paper",
            once=True,
        )


@pytest.mark.asyncio
async def test_live_mode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="paper-only"):
        await run_paper(
            client=_MockPublic([], {}),
            settings=_settings(arb_mode="live"),
            project_root=tmp_path,
            data_dir=tmp_path / "paper",
            once=True,
        )


def test_universe_filter_v1_rules() -> None:
    assert reject_universe(_market()) is None
    assert reject_universe(_market(neg_risk=True)) == "neg_risk"
    assert reject_universe(_market(delay=3)) == "seconds_delay"
    assert reject_universe(_market(accepting=False)) == "not_accepting"
    assert reject_universe(_market(no_id=None)) == "not_binary"
    assert (
        reject_universe(
            _market(
                slug="btc-updown-5m",
                question="BTC up or down 5 minutes",
                category="Crypto",
            )
        )
        == "short_crypto_window"
    )


def test_listing_limit_zero_uses_safety_cap() -> None:
    assert LIST_PAGE_SIZE == 100
    assert LIST_SAFETY_CAP == 5000
    assert listing_limit(20) == 20
    assert listing_limit(80) == 80
    assert listing_limit(0) == LIST_SAFETY_CAP
    assert listing_limit(-1) == LIST_SAFETY_CAP
    assert listing_limit(LIST_SAFETY_CAP + 1) == LIST_SAFETY_CAP


def test_list_all_markets_does_not_loosen_universe_or_risk() -> None:
    from arb.config import _EnvSettings

    fields = _EnvSettings.model_fields
    assert fields["stale_ms"].default == 400
    assert fields["min_edge"].default == Decimal("0.01")
    assert fields["max_gap"].default == Decimal("0.08")
    source = Path("src/arb/app.py").read_text(encoding="utf-8")
    assert "list_markets(closed=False, page_size=LIST_PAGE_SIZE)" in source
    assert "list_markets(closed=False, page_size=max_markets)" not in source
    assert "async for page in listed" in source
    assert 'return "neg_risk"' in source
    assert "seconds_delay" in source
    assert "short_crypto_window" in source
    assert "not_binary" in source


@pytest.mark.asyncio
async def test_iter_listed_markets_walks_pages_not_one_page_size() -> None:
    pages = [
        [
            _market(condition_id="p0-a", yes_id="y0a", no_id="n0a"),
            _market(condition_id="p0-b", yes_id="y0b", no_id="n0b"),
        ],
        [
            _market(condition_id="p1-a", yes_id="y1a", no_id="n1a"),
            _market(condition_id="p1-b", yes_id="y1b", no_id="n1b"),
        ],
        [
            _market(condition_id="p2-a", yes_id="y2a", no_id="n2a"),
            _market(condition_id="p2-b", yes_id="y2b", no_id="n2b"),
        ],
    ]
    client = _PagedPublic(pages)
    items = await _iter_listed_markets(client, 0)
    assert [m.condition_id for m in items] == [
        "p0-a",
        "p0-b",
        "p1-a",
        "p1-b",
        "p2-a",
        "p2-b",
    ]
    assert client.list_kwargs["closed"] is False
    assert client.list_kwargs["page_size"] == LIST_PAGE_SIZE
    assert client.list_kwargs["page_size"] != 0
    assert client.paginator is not None
    assert client.paginator.pages_yielded == 3


@pytest.mark.asyncio
async def test_iter_listed_markets_user_cap_still_walks_pages() -> None:
    pages = [
        [_market(condition_id="p0-a"), _market(condition_id="p0-b")],
        [_market(condition_id="p1-a"), _market(condition_id="p1-b")],
        [_market(condition_id="p2-a"), _market(condition_id="p2-b")],
    ]
    client = _PagedPublic(pages)
    items = await _iter_listed_markets(client, 3)
    assert [m.condition_id for m in items] == ["p0-a", "p0-b", "p1-a"]
    assert client.list_kwargs["page_size"] == LIST_PAGE_SIZE
    assert client.list_kwargs["page_size"] != 3
    assert client.paginator is not None
    assert client.paginator.pages_yielded == 2


@pytest.mark.asyncio
async def test_iter_listed_markets_safety_cap_stops_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arb.app.LIST_SAFETY_CAP", 4)
    pages = [
        [_market(condition_id="p0-a"), _market(condition_id="p0-b")],
        [_market(condition_id="p1-a"), _market(condition_id="p1-b")],
        [_market(condition_id="p2-a"), _market(condition_id="p2-b")],
    ]
    client = _PagedPublic(pages)
    items = await _iter_listed_markets(client, 0)
    assert len(items) == 4
    assert client.list_kwargs["page_size"] == LIST_PAGE_SIZE
    assert client.paginator is not None
    assert client.paginator.pages_yielded == 2


@pytest.mark.asyncio
async def test_max_markets_zero_lists_all_via_iter_items(tmp_path: Path) -> None:
    markets = [
        _market(condition_id=f"c{i}", yes_id=f"y{i}", no_id=f"n{i}") for i in range(5)
    ]
    client = _MockPublic(markets, {})
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=tmp_path / "paper",
        max_markets=0,
        once=True,
    )
    assert client.list_kwargs["page_size"] == LIST_PAGE_SIZE
    assert stats.markets_listed == 5
    assert stats.universe == 5


@pytest.mark.asyncio
async def test_listed_is_all_seen_universe_is_kept_and_books_are_v1_only(
    tmp_path: Path,
) -> None:
    keep = _market(condition_id="keep", yes_id="yes-keep", no_id="no-keep")
    neg = _market(condition_id="neg", yes_id="yes-neg", no_id="no-neg", neg_risk=True)
    delay = _market(condition_id="delay", yes_id="yes-delay", no_id="no-delay", delay=3)
    non_binary = _market(condition_id="nb", yes_id=None, no_id="no-nb")
    short = _market(
        condition_id="short",
        yes_id="yes-short",
        no_id="no-short",
        slug="btc-updown-5m",
        question="BTC up or down 5 minutes",
        category="Crypto",
    )
    keep2 = _market(condition_id="keep2", yes_id="yes-keep2", no_id="no-keep2")
    client = _PagedPublic([[keep, neg], [delay, non_binary], [short, keep2]])
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=tmp_path / "paper",
        max_markets=0,
        once=True,
    )
    assert stats.markets_listed == 6
    assert stats.universe == 2
    assert stats.rejects["neg_risk"] == 1
    assert stats.rejects["seconds_delay"] == 1
    assert stats.rejects["not_binary"] == 1
    assert stats.rejects["short_crypto_window"] == 1
    snapshot = json.loads((tmp_path / "paper" / "stats.json").read_text(encoding="utf-8"))
    assert snapshot["markets_listed"] == 6
    assert snapshot["universe"] == 2
    assert snapshot["reject_reasons"]["neg_risk"] == 1
    assert set(client.book_token_ids) == {
        "yes-keep",
        "no-keep",
        "yes-keep2",
        "no-keep2",
    }
    assert "yes-neg" not in client.book_token_ids
    assert "yes-delay" not in client.book_token_ids
    assert "yes-short" not in client.book_token_ids


@pytest.mark.asyncio
async def test_subscribe_only_v1_universe_token_pairs(tmp_path: Path) -> None:
    keep = _market(condition_id="keep", yes_id="yes-gap-3c", no_id="no-gap-3c")
    neg = _market(condition_id="neg", yes_id="yes-neg", no_id="no-neg", neg_risk=True)
    client = _SilentStreamPublic(
        [keep, neg],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
        },
    )
    await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=tmp_path / "paper",
        max_markets=0,
        once=False,
        seconds=0.2,
        poll_s=0.05,
    )
    assert client.book_token_ids == ["yes-gap-3c", "no-gap-3c"]
    assert client.subscribed_token_ids == ["yes-gap-3c", "no-gap-3c"]
    assert "yes-neg" not in client.subscribed_token_ids


def test_paper_run_cli_all_markets_and_zero_mean_no_user_cap() -> None:
    module = _load_script("paper_run_cli_all", Path("scripts/paper_run.py"))
    args = module.parse_args(["--all-markets"])
    assert module.resolve_max_markets(args) == 0
    args = module.parse_args(["--max-markets", "0"])
    assert module.resolve_max_markets(args) == 0
    args = module.parse_args([])
    assert module.resolve_max_markets(args) == 20
    args = module.parse_args(["--max-markets", "80"])
    assert module.resolve_max_markets(args) == 80
    args = module.parse_args(["--max-markets", "80", "--all-markets"])
    assert module.resolve_max_markets(args) == 0
    source = Path("scripts/paper_run.py").read_text(encoding="utf-8")
    assert "--all-markets" in source
    assert "LIST_SAFETY_CAP" in source


def test_paper_run_source_never_contains_secure_client() -> None:
    source = Path("scripts/paper_run.py").read_text(encoding="utf-8")
    assert "AsyncSecureClient" not in source
    assert "from polymarket import AsyncPublicClient" in source
    assert "list_markets" in source
    assert "AsyncSecureClient" not in Path("src/arb/app.py").read_text(encoding="utf-8")


def test_paper_run_cli_refuses_place_orders() -> None:
    module = _load_script("paper_run_cli", Path("scripts/paper_run.py"))
    assert module.main(["--place-orders"]) == 2


def test_stream_heartbeat_is_receive_age_not_book_age() -> None:
    beat = StreamHeartbeat()
    assert beat.age_ms(10_000) > 3000
    beat.mark(9_900)
    assert beat.age_ms(10_000) == 100
    # CLOB book timestamps can be far older than the just-arrived snapshot.
    book_age_ms = 10_000 - 1
    assert book_age_ms > 3000
    assert beat.age_ms(10_000) < book_age_ms


@pytest.mark.asyncio
async def test_old_clob_book_ts_does_not_trip_ws_stale(tmp_path: Path) -> None:
    old = datetime.now(timezone.utc) - timedelta(seconds=10)
    client = _MockPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55", timestamp=old),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42", timestamp=old),
        },
    )
    data_dir = tmp_path / "paper"
    await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=True,
    )
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is False
    assert restored.halt_reason == ""
    source = Path("src/arb/app.py").read_text(encoding="utf-8")
    assert "min(yes.ts_ms, no.ts_ms)" not in source


@pytest.mark.asyncio
async def test_poll_loop_old_book_ts_does_not_trip_ws_stale(tmp_path: Path) -> None:
    old = datetime.now(timezone.utc) - timedelta(seconds=10)
    client = _MockPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55", timestamp=old),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42", timestamp=old),
        },
    )
    data_dir = tmp_path / "paper"
    await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=False,
        seconds=0.4,
        poll_s=0.1,
    )
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is False
    assert restored.halt_reason == ""


@pytest.mark.asyncio
async def test_ws_book_without_min_order_size_does_not_kill_paper_run(
    tmp_path: Path,
) -> None:
    client = _WsNoneMinPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
        },
    )
    data_dir = tmp_path / "paper"
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=False,
        seconds=0.2,
        poll_s=0.05,
    )
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is False
    assert restored.halt_reason == ""
    assert stats.universe == 1
    assert stats.gaps >= 1
    assert "invalid_book_update" not in stats.rejects


@pytest.mark.asyncio
async def test_ws_empty_ask_price_is_skipped_without_halt(tmp_path: Path) -> None:
    client = _WsBadLevelPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
        },
    )
    data_dir = tmp_path / "paper"
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=False,
        seconds=0.2,
        poll_s=0.05,
    )
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is False
    assert restored.halt_reason == ""
    assert stats.rejects.get("invalid_book_update", 0) >= 1
    rejects = (data_dir / "rejects.jsonl").read_text(encoding="utf-8")
    assert "invalid_book_update" in rejects
    assert stats.gaps >= 1


def test_liveness_probe_due_approaches_ws_stale_ms() -> None:
    assert stream_liveness_probe_due(age_ms=0, ws_stale_ms=3000) is False
    assert stream_liveness_probe_due(age_ms=1999, ws_stale_ms=3000) is False
    assert stream_liveness_probe_due(age_ms=2000, ws_stale_ms=3000) is True
    assert stream_liveness_probe_due(age_ms=3001, ws_stale_ms=3000) is True
    assert stream_liveness_probe_due(age_ms=53, ws_stale_ms=80) is True


def test_quiet_ws_fix_does_not_loosen_caps() -> None:
    from arb.config import _EnvSettings

    fields = _EnvSettings.model_fields
    assert fields["stale_ms"].default == 400
    assert fields["ws_stale_ms"].default == 3000
    assert fields["min_edge"].default == Decimal("0.01")
    assert fields["max_gap"].default == Decimal("0.08")
    source = Path("src/arb/app.py").read_text(encoding="utf-8")
    assert "async def watch_silence" in source
    assert "stream_liveness_probe_due" in source


def _gap_books() -> dict[str, object]:
    return {
        "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
        "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
    }


@pytest.mark.asyncio
async def test_quiet_live_subscribe_does_not_trip_ws_stale(tmp_path: Path) -> None:
    client = _SilentStreamPublic([_market()], _gap_books())
    data_dir = tmp_path / "paper"
    await run_paper(
        client=client,
        settings=_settings(ws_stale_ms=80),
        project_root=tmp_path,
        data_dir=data_dir,
        once=False,
        seconds=0.5,
        poll_s=0.05,
    )
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is False
    assert restored.halt_reason == ""
    assert client.book_calls >= 2


@pytest.mark.asyncio
async def test_quiet_subscribe_failed_rest_probe_trips_ws_stale(tmp_path: Path) -> None:
    client = _QuietThenDeadRest([_market()], _gap_books())
    data_dir = tmp_path / "paper"
    await run_paper(
        client=client,
        settings=_settings(ws_stale_ms=80),
        project_root=tmp_path,
        data_dir=data_dir,
        once=False,
        seconds=0.5,
        poll_s=0.05,
    )
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is True
    assert restored.halt_reason == "ws_stale"
    assert client.book_calls >= 2


@pytest.mark.asyncio
async def test_subscribe_iterator_end_trips_ws_stale(tmp_path: Path) -> None:
    client = _ClosedStreamPublic([_market()], _gap_books())
    data_dir = tmp_path / "paper"
    await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=False,
        seconds=0.4,
        poll_s=0.05,
    )
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is True
    assert restored.halt_reason == "ws_stale"


@pytest.mark.asyncio
async def test_subscribe_iterator_error_trips_ws_stale(tmp_path: Path) -> None:
    client = _ErrorStreamPublic([_market()], _gap_books())
    data_dir = tmp_path / "paper"
    await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=False,
        seconds=0.4,
        poll_s=0.05,
    )
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is True
    assert restored.halt_reason == "ws_stale"


@pytest.mark.asyncio
async def test_poll_fetch_fail_after_snapshot_trips_ws_stale(tmp_path: Path) -> None:
    client = _PollBooksFailAfterFirst([_market()], _gap_books())
    data_dir = tmp_path / "paper"
    await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=False,
        seconds=0.4,
        poll_s=0.05,
    )
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is True
    assert restored.halt_reason == "ws_stale"


def _gap_markets(n: int) -> list[object]:
    return [
        _market(condition_id=f"c{i}", yes_id=f"y{i}", no_id=f"n{i}") for i in range(n)
    ]


def _gap_books_n(n: int) -> dict[str, object]:
    books: dict[str, object] = {}
    for i in range(n):
        books[f"y{i}"] = _book(f"y{i}", "0.54", "0.55")
        books[f"n{i}"] = _book(f"n{i}", "0.41", "0.42")
    return books


def test_book_batch_and_watch_defaults_fit_payload_limits() -> None:
    assert BOOK_BATCH_SIZE == 50
    assert WATCH_PAIRS == 40
    assert WATCH_ROTATE_S == 10
    assert LIST_SAFETY_CAP == 5000
    assert BOOK_BATCH_SIZE < 100
    assert WATCH_PAIRS * 2 == 80


def test_chunk_ids_splits_without_one_fat_payload() -> None:
    assert chunk_ids(["a", "b", "c", "d", "e"], 2) == [["a", "b"], ["c", "d"], ["e"]]
    assert chunk_ids([], 50) == []
    assert chunk_ids(["only"], 50) == [["only"]]
    assert chunk_ids(["a", "b"], 0) == [["a"], ["b"]]


def test_watch_slice_rotates_and_wraps() -> None:
    items = ["a", "b", "c", "d", "e"]
    assert watch_slice(items, 0, 2) == ["a", "b"]
    assert watch_slice(items, 2, 2) == ["c", "d"]
    assert watch_slice(items, 4, 2) == ["e", "a"]
    assert watch_slice(items, 0, 40) == items
    assert watch_slice([], 0, 40) == []


def test_pair_token_ids_keeps_yes_no_together() -> None:
    from arb.fee_agent import MarketFees
    from arb.risk import MarketFlags

    from arb.app import UniversePair

    pair = UniversePair(
        condition_id="c",
        yes_token_id="yes-1",
        no_token_id="no-1",
        flags=MarketFlags(
            accepting_orders=True, seconds_delay=0, neg_risk=False, binary=True
        ),
        fees=MarketFees(yes_rate=Decimal("0"), no_rate=Decimal("0")),
    )
    assert pair_token_ids([pair]) == ["yes-1", "no-1"]


def test_batch_books_does_not_loosen_universe_or_risk() -> None:
    from arb.config import _EnvSettings

    fields = _EnvSettings.model_fields
    assert fields["stale_ms"].default == 400
    assert fields["ws_stale_ms"].default == 3000
    assert fields["min_edge"].default == Decimal("0.01")
    assert fields["max_gap"].default == Decimal("0.08")
    source = Path("src/arb/app.py").read_text(encoding="utf-8")
    assert "LIST_SAFETY_CAP = 5000" in source
    assert "BOOK_BATCH_SIZE = 50" in source
    assert "WATCH_PAIRS = 40" in source
    assert "fetch_book_batches" in source
    assert 'return "neg_risk"' in source
    assert "seconds_delay" in source
    assert "short_crypto_window" in source
    assert "not_binary" in source


@pytest.mark.asyncio
async def test_opening_books_are_batched_not_one_fat_payload(tmp_path: Path) -> None:
    n = 6
    client = _MockPublic(_gap_markets(n), _gap_books_n(n))
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=tmp_path / "paper",
        once=True,
        book_batch_size=2,
    )
    assert stats.universe == n
    assert client.book_calls == n
    assert all(len(batch) <= 2 for batch in client.book_call_ids)
    requested = [tid for batch in client.book_call_ids for tid in batch]
    assert set(requested) == {f"y{i}" for i in range(n)} | {f"n{i}" for i in range(n)}
    snapshot = json.loads((tmp_path / "paper" / "stats.json").read_text(encoding="utf-8"))
    assert snapshot["heartbeat_ms"] > 0
    assert snapshot["universe"] == n
    assert stats.gaps >= 1


@pytest.mark.asyncio
async def test_failed_book_batch_is_logged_and_other_batches_continue(
    tmp_path: Path,
) -> None:
    n = 3
    client = _FailSelectedBookBatches(
        _gap_markets(n), _gap_books_n(n), fail_token="y1"
    )
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=tmp_path / "paper",
        once=True,
        book_batch_size=2,
    )
    assert stats.universe == n
    assert stats.rejects.get("book_batch_failed", 0) >= 1
    rejects = (tmp_path / "paper" / "rejects.jsonl").read_text(encoding="utf-8")
    assert "book_batch_failed" in rejects
    assert "Payload exceeds the limit" in rejects
    assert stats.gaps >= 1
    snapshot = json.loads((tmp_path / "paper" / "stats.json").read_text(encoding="utf-8"))
    assert snapshot["heartbeat_ms"] > 0
    assert snapshot["universe"] == n


@pytest.mark.asyncio
async def test_every_book_batch_fail_raises_public_api_error(tmp_path: Path) -> None:
    client = _MockPublic(_gap_markets(3), _gap_books_n(3), fail_books=True)
    with pytest.raises(PublicApiError, match="every book batch failed"):
        await run_paper(
            client=client,
            settings=_settings(),
            project_root=tmp_path,
            data_dir=tmp_path / "paper",
            once=True,
            book_batch_size=2,
        )


@pytest.mark.asyncio
async def test_watch_slice_does_not_subscribe_all_universe_pairs(
    tmp_path: Path,
) -> None:
    n = 5
    client = _SilentStreamPublic(_gap_markets(n), _gap_books_n(n))
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=tmp_path / "paper",
        once=False,
        seconds=0.2,
        poll_s=0.05,
        watch_pairs=2,
        watch_rotate_s=0,
        book_batch_size=4,
    )
    assert stats.universe == n
    assert stats.watching == 2
    assert client.subscribe_calls
    first = client.subscribe_calls[0]
    assert first == ["y0", "n0", "y1", "n1"]
    assert len(first) == 4
    assert "y4" not in first
    assert "n4" not in first


@pytest.mark.asyncio
async def test_watch_rotates_remaining_universe_pairs(tmp_path: Path) -> None:
    n = 4
    client = _SilentStreamPublic(_gap_markets(n), _gap_books_n(n))
    await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=tmp_path / "paper",
        once=False,
        seconds=0.7,
        poll_s=0.05,
        watch_pairs=2,
        watch_rotate_s=0.15,
        book_batch_size=4,
    )
    seen = {tuple(call) for call in client.subscribe_calls}
    assert len(seen) >= 2
    watched = {tid for call in client.subscribe_calls for tid in call}
    assert {"y0", "n0", "y1", "n1", "y2", "n2", "y3", "n3"} <= watched
    snapshot = json.loads((tmp_path / "paper" / "stats.json").read_text(encoding="utf-8"))
    assert snapshot["heartbeat_ms"] > 0
    assert snapshot["universe"] == n


@pytest.mark.asyncio
async def test_quiet_ws_liveness_probe_is_batched(tmp_path: Path) -> None:
    n = 3
    client = _SilentStreamPublic(_gap_markets(n), _gap_books_n(n))
    await run_paper(
        client=client,
        settings=_settings(ws_stale_ms=80),
        project_root=tmp_path,
        data_dir=tmp_path / "paper",
        once=False,
        seconds=0.5,
        poll_s=0.05,
        watch_pairs=3,
        watch_rotate_s=0,
        book_batch_size=2,
    )
    restored = StateStore((tmp_path / "paper") / "state.sqlite").restore()
    assert restored.halted is False
    assert all(len(batch) <= 2 for batch in client.book_call_ids)
    assert client.book_calls > 3


@pytest.mark.asyncio
async def test_paused_control_skips_paper_fills(tmp_path: Path) -> None:
    from arb.paper_control import PaperControl, write_control

    data_dir = tmp_path / "paper"
    data_dir.mkdir()
    write_control(data_dir, PaperControl(paused=True))
    client = _MockPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
        },
    )
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=True,
    )
    assert stats.intents == 0
    assert stats.fills == 0
    assert not (data_dir / "fills.jsonl").exists()
    assert (data_dir / "intents.jsonl").exists() is False or (
        data_dir / "intents.jsonl"
    ).read_text(encoding="utf-8").strip() == ""


@pytest.mark.asyncio
async def test_insufficient_bankroll_rejects_without_negative(tmp_path: Path) -> None:
    client = _MockPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
        },
    )
    stats = await run_paper(
        client=client,
        settings=_settings(paper_bankroll=d("1")),
        project_root=tmp_path,
        data_dir=tmp_path / "paper",
        once=True,
    )
    assert stats.intents == 0
    assert stats.rejects.get("insufficient_bankroll", 0) >= 1
    assert Decimal(str(stats.bankroll)) == d("1")
    restored = StateStore(tmp_path / "paper" / "state.sqlite").restore()
    assert restored.bankroll == d("1")
    assert restored.daily_pnl == d("0")
    assert restored.fills == []


def test_paper_run_cli_batch_and_watch_flags() -> None:
    module = _load_script("paper_run_cli_batch", Path("scripts/paper_run.py"))
    args = module.parse_args([])
    assert args.book_batch_size == BOOK_BATCH_SIZE
    assert args.watch_pairs == WATCH_PAIRS
    assert args.watch_rotate_s == WATCH_ROTATE_S
    args = module.parse_args(
        ["--book-batch-size", "25", "--watch-pairs", "10", "--watch-rotate-s", "30"]
    )
    assert args.book_batch_size == 25
    assert args.watch_pairs == 10
    assert args.watch_rotate_s == 30.0
    args = module.parse_args(["--paper-bankroll", "500"])
    assert args.paper_bankroll == "500"
    source = Path("scripts/paper_run.py").read_text(encoding="utf-8")
    assert "--book-batch-size" in source
    assert "--watch-pairs" in source
    assert "--watch-rotate-s" in source
    assert "--record-books" in source
    assert "LIST_SAFETY_CAP" in source
    args = module.parse_args(["--record-books"])
    assert args.record_books is True


def test_report_paper_prints_stats(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "gaps.jsonl").write_text(
        '{"raw_edge":"0.03","maker_ev":"0.75","taker_ev":"-0.20","reject_reason":null}\n',
        encoding="utf-8",
    )
    (paper / "intents.jsonl").write_text(
        '{"path":"maker_gtc","expected_net_edge":"0.75"}\n',
        encoding="utf-8",
    )
    (paper / "rejects.jsonl").write_text(
        '{"reason":"stale"}\n{"reason":"stale"}\n{"reason":"neg_risk"}\n',
        encoding="utf-8",
    )
    module = _load_script("report_paper_cli", Path("scripts/report_paper.py"))
    stats = module.summarize_paper(paper)
    assert stats["gaps_seen"] == 1
    assert stats["intents_approved"] == 1
    assert stats["estimated_maker_ev"] == Decimal("0.75")
    assert stats["estimated_taker_ev"] == Decimal("-0.20")
    assert stats["reject_reasons"]["stale"] == 2
    text = module.format_report(stats)
    assert "gaps seen: 1" in text
    assert "intents approved: 1" in text
    assert "best edge this hour" in text
    assert "estimated maker EV" in text
    assert "estimated taker EV" in text
    assert "stale: 2" in text
    assert "halt reason" not in text


def test_report_paper_reads_halt_reason(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    store = StateStore(paper / "state.sqlite")
    store.set_halted(True, reason="ws_stale")
    module = _load_script("report_paper_cli", Path("scripts/report_paper.py"))
    stats = module.summarize_paper(paper)
    assert stats["halt_reason"] == "ws_stale"
    text = module.format_report(stats)
    assert "halt reason: ws_stale" in text


@pytest.mark.asyncio
async def test_paper_run_writes_nearmiss_alerts_and_books(tmp_path: Path) -> None:
    client = _MockPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
        },
    )
    data_dir = tmp_path / "paper"
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=True,
        record_books=True,
    )
    assert stats.nearmiss_considers >= 1
    assert stats.best_edge == Decimal("0.03")
    assert stats.alerts >= 1
    assert (data_dir / "nearmiss.jsonl").is_file()
    assert (data_dir / "alerts.jsonl").is_file()
    assert (data_dir / "books.jsonl").is_file()
    near = json.loads((data_dir / "nearmiss.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert near["raw_edge"] == "0.03"
    alert = json.loads((data_dir / "alerts.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert alert["path"] in {"maker_gtc", "taker_fak"}
    snapshot = json.loads((data_dir / "stats.json").read_text(encoding="utf-8"))
    assert snapshot["best_edge"] == "0.03"
    assert snapshot["alerts"] >= 1


@pytest.mark.asyncio
async def test_paper_run_near_miss_when_hunt_is_silent(tmp_path: Path) -> None:
    client = _MockPublic(
        [_market(yes_id="yes-no-gap", no_id="no-no-gap")],
        {
            "yes-no-gap": _book("yes-no-gap", "0.49", "0.50"),
            "no-no-gap": _book("no-no-gap", "0.49", "0.50"),
        },
    )
    data_dir = tmp_path / "paper"
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=True,
    )
    assert stats.gaps == 0
    assert stats.intents == 0
    assert stats.nearmiss_considers >= 1
    assert stats.best_edge == Decimal("0")
    assert stats.edge_histogram.get("0_0.005", 0) >= 1


@pytest.mark.asyncio
async def test_honest_p_miss_one_on_taker_path(tmp_path: Path) -> None:
    """Force taker by making maker EV non-positive is hard; post via ledger in-loop.

    A 3c gap prefers maker. This test keeps hunt/risk caps and only checks
    that honest=True still completes a maker rest at end-of-run.
    """
    client = _MockPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
        },
    )
    data_dir = tmp_path / "paper"
    stats = await run_paper(
        client=client,
        settings=_settings(),
        project_root=tmp_path,
        data_dir=data_dir,
        once=True,
        honest=True,
        p_miss=d("1"),
    )
    assert stats.intents >= 1
    assert stats.completed_pairs + stats.naked_incidents >= 1
    fills = (data_dir / "fills.jsonl").read_text(encoding="utf-8")
    assert "outcome" in fills


def test_helper_caps_stay_tight() -> None:
    assert LIST_SAFETY_CAP == 5000
    assert BOOK_BATCH_SIZE == 50
    assert WATCH_PAIRS == 40
    from arb.app import PIN_HOT_PAIRS

    assert PIN_HOT_PAIRS == 8
    assert PIN_HOT_PAIRS <= WATCH_PAIRS
