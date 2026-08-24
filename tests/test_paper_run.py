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

from arb.app import PublicApiError, StreamHeartbeat, reject_universe, run_paper
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
        self.list_kwargs: dict[str, object] = {}

    def list_markets(self, *, closed: bool = False, page_size: int = 20, **kwargs):
        self.list_kwargs = {"closed": closed, "page_size": page_size, **kwargs}
        if self.fail_list:
            raise ConnectionError("connection refused")
        return _Paginator(self.markets)

    async def get_order_books(self, *, token_ids: list[str]):
        if self.fail_books:
            raise TimeoutError("timed out")
        return [self.books[tid] for tid in token_ids if tid in self.books]


class _SilentStreamPublic(_MockPublic):
    """Public client whose websocket never delivers another event."""

    def subscribe(self, token_ids: list[str]):
        async def gen():
            while True:
                await asyncio.sleep(60)
                yield []

        return gen()


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
        async def gen():
            yield _ws_book("yes-gap-3c", "0.54", "0.55")
            yield _ws_book("no-gap-3c", "0.41", "0.42")

        return gen()


class _WsBadLevelPublic(_MockPublic):
    """One WS book has an empty ask price after a good REST snapshot."""

    def subscribe(self, token_ids: list[str]):
        async def gen():
            yield SimpleNamespace(
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

        return gen()


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
    gaps = (tmp_path / "paper" / "gaps.jsonl").read_text(encoding="utf-8").strip()
    assert "raw_edge" in gaps
    intents = (tmp_path / "paper" / "intents.jsonl").read_text(encoding="utf-8").strip()
    assert "maker_gtc" in intents


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


@pytest.mark.asyncio
async def test_ws_silence_after_snapshot_trips_kill_switch(tmp_path: Path) -> None:
    client = _SilentStreamPublic(
        [_market()],
        {
            "yes-gap-3c": _book("yes-gap-3c", "0.54", "0.55"),
            "no-gap-3c": _book("no-gap-3c", "0.41", "0.42"),
        },
    )
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
