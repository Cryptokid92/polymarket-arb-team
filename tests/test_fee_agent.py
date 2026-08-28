"""Task 6 contracts: prefer maker GTC; refuse negative-EV taker."""

from __future__ import annotations

import ast
import inspect
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from arb.books import BookStore, Level
from arb.fee_agent import MarketFees, choose_intent
from arb.fees import net_edge_maker, net_edge_taker, pair_taker_fees
from arb.hunter import hunt
from arb.maker import gap_from_maker_quotes, maker_complete_quotes
from arb.messages import GapFound, Intent
from arb.money import d

FIXTURES = Path(__file__).parent / "fixtures" / "books"
MIN_EDGE = d("0.01")
TAKER_BUFFER = d("0.005")
CRYPTO = MarketFees(yes_rate=d("0.07"), no_rate=d("0.07"))
FEE_FREE = MarketFees(yes_rate=d("0"), no_rate=d("0"))


def _type_includes_float(annotation: object) -> bool:
    origin = get_origin(annotation)
    if annotation is float:
        return True
    if origin is None:
        return annotation is float
    return any(arg is float for arg in get_args(annotation))


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


def _zero_edge_gap() -> GapFound:
    return GapFound(
        condition_id="zero-edge",
        yes_token_id="yes-zero",
        no_token_id="no-zero",
        yes_asks=[Level(price=d("0.50"), size=d("50"))],
        no_asks=[Level(price=d("0.50"), size=d("50"))],
        fillable_shares=d("50"),
        yes_vwap=d("0.50"),
        no_vwap=d("0.50"),
        raw_edge=d("0"),
        ts_ms=1000,
        book_age_ms=0,
    )


def test_crypto_3c_ask_take_is_none_when_taker_ev_non_positive() -> None:
    gap = _gap_3c()
    assert gap.yes_vwap == d("0.55")
    assert gap.no_vwap == d("0.42")
    assert gap.raw_edge == d("0.03")
    fees = pair_taker_fees(
        gap.fillable_shares,
        gap.yes_vwap,
        gap.fillable_shares,
        gap.no_vwap,
        CRYPTO.yes_rate,
        CRYPTO.no_rate,
    )
    taker_ev = net_edge_taker(gap.raw_edge, gap.fillable_shares, fees) - (
        TAKER_BUFFER * gap.fillable_shares
    )
    assert taker_ev <= 0
    assert net_edge_maker(gap.raw_edge, gap.fillable_shares) > 0
    assert choose_intent(gap, CRYPTO, MIN_EDGE) is None
    assert choose_intent(gap, CRYPTO, MIN_EDGE, source="taker") is None


def test_fee_free_3c_ask_take_is_taker_fak() -> None:
    gap = _gap_3c()
    intent = choose_intent(gap, FEE_FREE, MIN_EDGE)
    assert intent is not None
    assert intent.path == "taker_fak"
    assert intent.yes_limit == gap.yes_vwap
    assert intent.no_limit == gap.no_vwap
    fees = pair_taker_fees(
        gap.fillable_shares,
        gap.yes_vwap,
        gap.fillable_shares,
        gap.no_vwap,
        FEE_FREE.yes_rate,
        FEE_FREE.no_rate,
    )
    taker_ev = net_edge_taker(gap.raw_edge, gap.fillable_shares, fees) - (
        TAKER_BUFFER * gap.fillable_shares
    )
    assert taker_ev > 0
    assert intent.expected_net_edge == taker_ev
    assert intent.taker_fee_yes == Decimal("0")
    assert intent.taker_fee_no == Decimal("0")


def test_bid_rest_is_maker_gtc_even_when_taker_ev_non_positive() -> None:
    yes, no, _payload = _load_pair("no_gap.json")
    quotes = maker_complete_quotes(
        yes,
        no,
        min_edge=MIN_EDGE,
        max_gap=d("0.08"),
        min_size=yes.min_order_size,
        max_notional=d("25"),
        stale_ms=400,
        now_ms=1000,
    )
    assert quotes is not None
    gap = gap_from_maker_quotes(yes, no, quotes, 1000, "no-gap")
    intent = choose_intent(gap, CRYPTO, MIN_EDGE, source="maker")
    assert intent is not None
    assert intent.path == "maker_gtc"
    assert intent.yes_limit == d("0.49")
    assert intent.no_limit == d("0.49")
    assert intent.taker_fee_yes == Decimal("0")
    assert intent.taker_fee_no == Decimal("0")
    assert choose_intent(gap, CRYPTO, MIN_EDGE, source="taker") is None


def test_refuse_when_both_ev_non_positive() -> None:
    gap = _zero_edge_gap()
    assert net_edge_maker(gap.raw_edge, gap.fillable_shares) <= 0
    assert choose_intent(gap, FEE_FREE, d("0")) is None
    assert choose_intent(gap, CRYPTO, d("0")) is None
    assert choose_intent(gap, FEE_FREE, MIN_EDGE) is None


def test_choose_intent_never_uses_float_or_rebate() -> None:
    hints = get_type_hints(choose_intent)
    for name, annotation in hints.items():
        assert not _type_includes_float(annotation)
    source = inspect.getsource(choose_intent)
    assert "rebate" not in source.lower()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float"
        if isinstance(node, ast.Constant) and type(node.value) is float:
            raise AssertionError("choose_intent must not use float literals")
