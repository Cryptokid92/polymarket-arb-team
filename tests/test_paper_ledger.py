"""Paper bankroll, fills, and completeness settlement. Paper only."""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import pytest

from arb.books import BookStore
from arb.fee_agent import MarketFees
from arb.fees import maker_fee, net_edge_maker, net_edge_taker, pair_taker_fees
from arb.hunter import hunt
from arb.messages import GapFound, Intent
from arb.money import d
from arb.paper_ledger import (
    PaperLedger,
    completeness_pnl,
    pair_cost,
    pair_fees_for_intent,
)
from arb.state import StateStore

FIXTURES = Path(__file__).parent / "fixtures" / "books"
CRYPTO = MarketFees(yes_rate=d("0.07"), no_rate=d("0.07"))
FEE_FREE = MarketFees(yes_rate=d("0"), no_rate=d("0"))
MIN_EDGE = d("0.01")


def _type_includes_float(annotation: object) -> bool:
    origin = get_origin(annotation)
    if annotation is float:
        return True
    if origin is None:
        return annotation is float
    return any(arg is float for arg in get_args(annotation))


def _assert_no_secure_client(source: str) -> None:
    assert "AsyncSecureClient" not in source
    assert "from polymarket" not in source
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "AsyncSecureClient"


def _load_pair(name: str) -> tuple[Any, Any, dict[str, Any]]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    store = BookStore()
    yes = store.apply_snapshot(payload["yes"])
    no = store.apply_snapshot(payload["no"])
    return yes, no, payload


def _gap_3c() -> GapFound:
    yes, no, payload = _load_pair("gap_3c.json")
    found = hunt(yes, no, MIN_EDGE, yes.min_order_size, d(payload["max_shares"]), now_ms=1000)
    assert found is not None
    return found


def _maker_intent(size: Decimal | None = None) -> Intent:
    gap = _gap_3c()
    if size is not None:
        gap = gap.model_copy(update={"fillable_shares": size})
    return Intent(
        gap=gap,
        path="maker_gtc",
        size=gap.fillable_shares if size is None else size,
        yes_limit=gap.yes_vwap,
        no_limit=gap.no_vwap,
        expected_net_edge=net_edge_maker(gap.raw_edge, gap.fillable_shares if size is None else size),
        taker_fee_yes=d("0"),
        taker_fee_no=d("0"),
    )


def _taker_intent(size: Decimal = d("10")) -> Intent:
    gap = _gap_3c().model_copy(update={"fillable_shares": size})
    yes_fee = pair_taker_fees(size, gap.yes_vwap, d("0"), gap.no_vwap, CRYPTO.yes_rate, d("0"))
    no_fee = pair_taker_fees(d("0"), gap.yes_vwap, size, gap.no_vwap, d("0"), CRYPTO.no_rate)
    return Intent(
        gap=gap,
        path="taker_fak",
        size=size,
        yes_limit=gap.yes_vwap,
        no_limit=gap.no_vwap,
        expected_net_edge=d("0.01"),
        taker_fee_yes=yes_fee,
        taker_fee_no=no_fee,
    )


def test_makers_pay_zero_pair_fees() -> None:
    intent = _maker_intent(d("10"))
    assert pair_fees_for_intent(intent, CRYPTO) == Decimal("0")
    assert maker_fee(d("10"), d("0.55"), d("0.07")) == Decimal("0")


def test_taker_pair_fees_use_protocol_helpers() -> None:
    intent = _taker_intent(d("10"))
    expected = pair_taker_fees(
        d("10"), d("0.55"), d("10"), d("0.42"), d("0.07"), d("0.07")
    )
    assert pair_fees_for_intent(intent, CRYPTO) == expected
    assert expected == Decimal("0.34")


def test_completeness_pnl_is_one_minus_vwaps_minus_fees() -> None:
    maker = _maker_intent(d("10"))
    assert completeness_pnl(maker, CRYPTO) == Decimal("0.30")
    assert completeness_pnl(maker, CRYPTO) == net_edge_maker(d("0.03"), d("10"))
    taker = _taker_intent(d("10"))
    fees = pair_taker_fees(d("10"), d("0.55"), d("10"), d("0.42"), d("0.07"), d("0.07"))
    assert completeness_pnl(taker, CRYPTO) == net_edge_taker(d("0.03"), d("10"), fees)
    assert completeness_pnl(taker, CRYPTO) == Decimal("-0.04")


def test_pair_cost_is_size_times_vwaps_plus_fees() -> None:
    maker = _maker_intent(d("10"))
    assert pair_cost(maker, CRYPTO) == Decimal("9.70")
    taker = _taker_intent(d("10"))
    assert pair_cost(taker, CRYPTO) == Decimal("10.04")


def test_paper_ledger_honest_kwarg_defaults_true() -> None:
    default = inspect.signature(PaperLedger.__init__).parameters["honest"].default
    assert default is True


@pytest.mark.asyncio
async def test_maker_fill_settles_and_updates_bankroll(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(store, bankroll=d("500"), daily_pnl=d("0"), honest=False)
    result = await ledger.try_fill(_maker_intent(d("10")), CRYPTO, now_ms=1_000)
    assert result.accepted is True
    assert result.reject_reason is None
    assert result.pair_fees == Decimal("0")
    assert result.cost == Decimal("9.70")
    assert result.pnl == Decimal("0.30")
    assert result.bankroll == Decimal("500.30")
    assert result.daily_pnl == Decimal("0.30")
    restored = store.restore()
    assert restored.bankroll == Decimal("500.30")
    assert restored.daily_pnl == Decimal("0.30")
    assert len(restored.fills) == 2
    assert restored.inventory[result.condition_id] == (Decimal("0"), Decimal("0"))


@pytest.mark.asyncio
async def test_taker_fill_subtracts_protocol_fees(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(store, bankroll=d("500"), daily_pnl=d("0"), honest=False)
    result = await ledger.try_fill(_taker_intent(d("10")), CRYPTO, now_ms=2_000)
    assert result.accepted is True
    assert result.pair_fees == Decimal("0.34")
    assert result.pnl == Decimal("-0.04")
    assert result.bankroll == Decimal("499.96")
    assert result.daily_pnl == Decimal("-0.04")


@pytest.mark.asyncio
async def test_refuse_when_cost_exceeds_bankroll(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(store, bankroll=d("1"), daily_pnl=d("0"))
    result = await ledger.try_fill(_maker_intent(d("10")), CRYPTO, now_ms=3_000)
    assert result.accepted is False
    assert result.reject_reason == "insufficient_bankroll"
    assert result.bankroll == Decimal("1")
    assert result.daily_pnl == Decimal("0")
    restored = store.restore()
    assert restored.fills == []
    assert restored.bankroll is None
    assert ledger.bankroll == Decimal("1")


@pytest.mark.asyncio
async def test_equal_bankroll_and_cost_is_allowed(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    intent = _maker_intent(d("10"))
    cost = pair_cost(intent, FEE_FREE)
    ledger = PaperLedger(store, bankroll=cost, daily_pnl=d("0"), honest=False)
    result = await ledger.try_fill(intent, FEE_FREE, now_ms=4_000)
    assert result.accepted is True
    assert result.bankroll == cost + result.pnl
    assert result.bankroll > Decimal("0")


@pytest.mark.asyncio
async def test_live_mode_is_refused(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(store, bankroll=d("500"), daily_pnl=d("0"))
    with pytest.raises(RuntimeError, match="will not fill live"):
        await ledger.try_fill(_maker_intent(d("10")), CRYPTO, now_ms=5_000, mode="live")


@pytest.mark.asyncio
async def test_honest_taker_miss_is_naked_hedge(tmp_path: Path) -> None:
    yes, no, _payload = _load_pair("gap_3c.json")
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(
        store,
        bankroll=d("500"),
        daily_pnl=d("0"),
        honest=True,
        p_miss=d("1"),
        rng_seed=1,
        hedge_slippage=d("0.01"),
    )
    result = await ledger.try_fill(
        _taker_intent(d("10")), CRYPTO, now_ms=6_000, yes=yes, no=no
    )
    assert result.accepted is True
    assert result.outcome == "naked"
    assert result.naked is True
    assert result.completed is False
    assert result.pnl < Decimal("0")
    assert store.hedge_incidents_since(0) == 1


@pytest.mark.asyncio
async def test_honest_maker_rests_then_cancels_when_touch_holds(tmp_path: Path) -> None:
    yes, no, _payload = _load_pair("gap_3c.json")
    books = BookStore()
    _put_book(books, yes.token_id, "0.54", "0.55")
    _put_book(books, no.token_id, "0.41", "0.42")
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(
        store,
        bankroll=d("500"),
        daily_pnl=d("0"),
        honest=True,
        maker_rest_ms=400,
    )
    first = await ledger.try_fill(
        _bid_maker_intent(d("10")), FEE_FREE, now_ms=1_000, yes=yes, no=no
    )
    assert first.outcome == "resting"
    assert first.pnl == Decimal("0")
    assert ledger.bankroll == Decimal("500")
    later = await ledger.poll_rests(books, now_ms=1_400)
    assert len(later) == 1
    assert later[0].outcome == "canceled"
    assert later[0].completed is False
    assert later[0].pnl == Decimal("0")


@pytest.mark.asyncio
async def test_default_honest_maker_rests_then_cancels_when_touch_holds(
    tmp_path: Path,
) -> None:
    yes, no, _payload = _load_pair("gap_3c.json")
    books = BookStore()
    _put_book(books, yes.token_id, "0.54", "0.55")
    _put_book(books, no.token_id, "0.41", "0.42")
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(store, bankroll=d("500"), daily_pnl=d("0"))
    first = await ledger.try_fill(
        _bid_maker_intent(d("10")), FEE_FREE, now_ms=1_000, yes=yes, no=no
    )
    assert first.outcome == "resting"
    assert first.pnl == Decimal("0")
    assert first.completed is False
    assert ledger.bankroll == Decimal("500")
    later = await ledger.poll_rests(books, now_ms=1_400)
    assert len(later) == 1
    assert later[0].outcome == "canceled"
    assert later[0].completed is False
    assert later[0].pnl == Decimal("0")


@pytest.mark.asyncio
async def test_honest_maker_missing_book_does_not_complete(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(
        store,
        bankroll=d("500"),
        daily_pnl=d("0"),
        honest=True,
    )
    result = await ledger.try_fill(
        _maker_intent(d("10")), FEE_FREE, now_ms=1_000, yes=None
    )
    assert result.completed is False
    assert result.pnl == Decimal("0")
    assert result.outcome in {"resting", "rejected", "canceled"}
    assert ledger.bankroll == Decimal("500")
    restored = store.restore()
    assert restored.fills == []
    assert restored.bankroll is None


@pytest.mark.asyncio
async def test_honest_maker_rests_then_fills_on_ask_through(tmp_path: Path) -> None:
    yes, no, _payload = _load_pair("gap_3c.json")
    books = BookStore()
    _put_book(books, yes.token_id, "0.54", "0.55")
    _put_book(books, no.token_id, "0.41", "0.42")
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(
        store,
        bankroll=d("500"),
        daily_pnl=d("0"),
        honest=True,
        maker_rest_ms=400,
    )
    first = await ledger.try_fill(
        _bid_maker_intent(d("10")), FEE_FREE, now_ms=1_000, yes=yes, no=no
    )
    assert first.outcome == "resting"
    _put_book(books, yes.token_id, "0.54", "0.54", ts_ms=1_400)
    _put_book(books, no.token_id, "0.41", "0.41", ts_ms=1_400)
    later = await ledger.poll_rests(books, now_ms=1_400)
    assert len(later) == 1
    assert later[0].outcome == "filled"
    assert later[0].completed is True
    assert later[0].pnl == Decimal("0.50")


@pytest.mark.asyncio
async def test_missing_books_after_timeout_cancel_rest_and_free_slot(
    tmp_path: Path,
) -> None:
    yes, no, _payload = _load_pair("gap_3c.json")
    books = BookStore()
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(
        store,
        bankroll=d("500"),
        daily_pnl=d("0"),
        honest=True,
        maker_rest_ms=400,
    )
    first = await ledger.try_fill(
        _maker_intent(d("10")), FEE_FREE, now_ms=1_000, yes=yes, no=no
    )
    assert first.outcome == "resting"
    assert ledger.resting_pairs == 1
    still = await ledger.poll_rests(books, now_ms=1_200)
    assert still == []
    assert ledger.resting_pairs == 1
    later = await ledger.poll_rests(books, now_ms=1_400)
    assert len(later) == 1
    assert later[0].outcome == "canceled"
    assert later[0].completed is False
    assert later[0].naked is False
    assert later[0].pnl == Decimal("0")
    assert ledger.resting_pairs == 0
    assert ledger.bankroll == Decimal("500")


def _put_book(
    store: BookStore,
    token_id: str,
    bid: str,
    ask: str,
    *,
    bid_size: str = "10",
    ask_size: str = "80",
    ts_ms: int = 1000,
) -> None:
    store.apply_snapshot(
        {
            "token_id": token_id,
            "bids": [{"price": bid, "size": bid_size}],
            "asks": [{"price": ask, "size": ask_size}],
            "tick": "0.01",
            "min_order_size": "5",
            "ts_ms": ts_ms,
        }
    )


def _bid_maker_intent(size: Decimal) -> Intent:
    gap = _gap_3c().model_copy(
        update={
            "fillable_shares": size,
            "yes_vwap": d("0.54"),
            "no_vwap": d("0.41"),
            "raw_edge": d("0.05"),
        }
    )
    return Intent(
        gap=gap,
        path="maker_gtc",
        size=size,
        yes_limit=d("0.54"),
        no_limit=d("0.41"),
        expected_net_edge=net_edge_maker(d("0.05"), size),
        taker_fee_yes=d("0"),
        taker_fee_no=d("0"),
    )


@pytest.mark.asyncio
async def test_one_sided_still_at_bid_cancels_instead_of_naked(
    tmp_path: Path,
) -> None:
    yes, no, _payload = _load_pair("gap_3c.json")
    books = BookStore()
    _put_book(books, yes.token_id, "0.54", "0.55")
    _put_book(books, no.token_id, "0.41", "0.42")
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(
        store,
        bankroll=d("500"),
        daily_pnl=d("0"),
        honest=True,
        maker_rest_ms=400,
    )
    first = await ledger.try_fill(
        _bid_maker_intent(d("10")), FEE_FREE, now_ms=1_000, yes=yes, no=no
    )
    assert first.outcome == "resting"
    _put_book(books, no.token_id, "0.40", "0.42", ts_ms=1_400)
    later = await ledger.poll_rests(books, now_ms=1_400)
    assert len(later) == 1
    assert later[0].outcome == "canceled"
    assert later[0].naked is False
    assert store.hedge_incidents_since(0) == 0
    assert ledger.resting_pairs == 0


@pytest.mark.asyncio
async def test_one_sided_take_still_hedges_naked(tmp_path: Path) -> None:
    yes, no, _payload = _load_pair("gap_3c.json")
    books = BookStore()
    _put_book(books, yes.token_id, "0.54", "0.55")
    _put_book(books, no.token_id, "0.41", "0.42")
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(
        store,
        bankroll=d("500"),
        daily_pnl=d("0"),
        honest=True,
        maker_rest_ms=400,
    )
    first = await ledger.try_fill(
        _bid_maker_intent(d("10")), FEE_FREE, now_ms=1_000, yes=yes, no=no
    )
    assert first.outcome == "resting"
    _put_book(books, yes.token_id, "0.53", "0.54", ts_ms=1_400)
    _put_book(books, no.token_id, "0.40", "0.42", ts_ms=1_400)
    later = await ledger.poll_rests(books, now_ms=1_400)
    assert len(later) == 1
    assert later[0].outcome == "naked"
    assert later[0].naked is True
    assert store.hedge_incidents_since(0) == 1


def test_ledger_never_uses_float_or_secure_client() -> None:
    import arb.paper_ledger as mod

    _assert_no_secure_client(inspect.getsource(mod))
    for helper in (pair_fees_for_intent, pair_cost, completeness_pnl):
        hints = get_type_hints(helper)
        for name, annotation in hints.items():
            assert not _type_includes_float(annotation), name
        source = inspect.getsource(helper)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and type(node.value) is float:
                raise AssertionError(f"{helper.__name__} must not use float literals")
