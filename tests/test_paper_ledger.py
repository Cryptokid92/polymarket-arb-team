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


@pytest.mark.asyncio
async def test_maker_fill_settles_and_updates_bankroll(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(store, bankroll=d("500"), daily_pnl=d("0"))
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
    ledger = PaperLedger(store, bankroll=d("500"), daily_pnl=d("0"))
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
    ledger = PaperLedger(store, bankroll=cost, daily_pnl=d("0"))
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


@pytest.mark.asyncio
async def test_settle_full_set_three_vwaps_pnl(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(store, bankroll=d("500"), daily_pnl=d("0"))
    result = await ledger.settle_full_set(
        (d("0.40"), d("0.30"), d("0.28")),
        d("5"),
        now_ms=6_000,
        event_id="evt-3way",
    )
    assert result.accepted is True
    assert result.reject_reason is None
    assert result.path == "fullset_taker"
    assert result.size == Decimal("5")
    assert result.cost == Decimal("4.90")
    assert result.pnl == Decimal("0.10")
    assert result.bankroll == Decimal("500.10")
    assert result.daily_pnl == Decimal("0.10")
    assert result.yes_vwap == Decimal("0.40")
    assert result.no_vwap == Decimal("0.30")
    assert result.condition_id == "evt-3way"
    restored = store.restore()
    assert restored.bankroll == Decimal("500.10")
    assert restored.daily_pnl == Decimal("0.10")
    assert len(restored.fills) == 3


@pytest.mark.asyncio
async def test_settle_full_set_live_mode_raises(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(store, bankroll=d("500"), daily_pnl=d("0"))
    with pytest.raises(RuntimeError, match="will not fill live"):
        await ledger.settle_full_set(
            (d("0.40"), d("0.30"), d("0.28")),
            d("5"),
            now_ms=7_000,
            mode="live",
        )


@pytest.mark.asyncio
async def test_settle_full_set_insufficient_bankroll(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    ledger = PaperLedger(store, bankroll=d("1"), daily_pnl=d("0"))
    result = await ledger.settle_full_set(
        (d("0.40"), d("0.30"), d("0.28")),
        d("5"),
        now_ms=8_000,
        event_id="evt-3way",
    )
    assert result.accepted is False
    assert result.reject_reason == "insufficient_bankroll"
    assert result.path == "fullset_taker"
    assert result.pnl == Decimal("0")
    assert result.bankroll == Decimal("1")
    assert result.daily_pnl == Decimal("0")
    restored = store.restore()
    assert restored.fills == []
    assert restored.bankroll is None
    assert ledger.bankroll == Decimal("1")
