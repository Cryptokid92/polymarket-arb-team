"""Task 4 contracts: hunter flags depth-sized ask gaps only."""

from __future__ import annotations

import ast
import inspect
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from arb.books import Book, BookStore, Level
from arb.hunter import hunt
from arb.messages import GapFound
from arb.money import d

FIXTURES = Path(__file__).parent / "fixtures" / "books"
MIN_EDGE = d("0.01")


def _type_includes_float(annotation: object) -> bool:
    origin = get_origin(annotation)
    if annotation is float:
        return True
    if origin is None:
        return annotation is float
    return any(arg is float for arg in get_args(annotation))


def _load_pair(name: str) -> tuple[Book, Book, dict[str, Any]]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    store = BookStore()
    yes = store.apply_snapshot(payload["yes"])
    no = store.apply_snapshot(payload["no"])
    return yes, no, payload


def test_gap_3c_emits_gapfound_with_raw_edge_0_03() -> None:
    yes, no, payload = _load_pair("gap_3c.json")
    found = hunt(
        yes,
        no,
        MIN_EDGE,
        yes.min_order_size,
        d(payload["max_shares"]),
        now_ms=1000,
    )
    assert isinstance(found, GapFound)
    assert found.fillable_shares == Decimal("80")
    assert found.yes_vwap + found.no_vwap == Decimal("0.97")
    assert found.raw_edge == Decimal("0.03")
    assert found.raw_edge == Decimal("1") - found.yes_vwap - found.no_vwap
    assert found.yes_token_id == yes.token_id
    assert found.no_token_id == no.token_id


def test_no_gap_is_silent() -> None:
    yes, no, payload = _load_pair("no_gap.json")
    found = hunt(
        yes,
        no,
        MIN_EDGE,
        yes.min_order_size,
        d(payload["max_shares"]),
        now_ms=1000,
    )
    assert found is None


def test_bid_only_completeness_is_not_a_signal() -> None:
    yes = Book(
        token_id="yes-bid-only",
        bids=[Level(price=d("0.40"), size=d("100"))],
        asks=[Level(price=d("0.51"), size=d("100"))],
        tick=d("0.01"),
        min_order_size=d("5"),
        ts_ms=1000,
    )
    no = Book(
        token_id="no-bid-only",
        bids=[Level(price=d("0.40"), size=d("100"))],
        asks=[Level(price=d("0.50"), size=d("100"))],
        tick=d("0.01"),
        min_order_size=d("5"),
        ts_ms=1000,
    )
    assert hunt(yes, no, MIN_EDGE, d("5"), d("100"), now_ms=1000) is None


def test_book_age_ms_uses_older_book_from_stale_one_side() -> None:
    yes, no, payload = _load_pair("stale_one_side.json")
    now_ms = int(payload["now_ms"])
    found = hunt(yes, no, MIN_EDGE, yes.min_order_size, d("20"), now_ms=now_ms)
    assert found is not None
    older = yes.ts_ms if yes.ts_ms < no.ts_ms else no.ts_ms
    assert older == 1000
    assert found.book_age_ms == now_ms - older
    assert found.book_age_ms == 9000


def test_hunt_does_not_size_from_bids() -> None:
    yes = Book(
        token_id="yes-fat-bids",
        bids=[Level(price=d("0.54"), size=d("500"))],
        asks=[Level(price=d("0.55"), size=d("3"))],
        tick=d("0.01"),
        min_order_size=d("5"),
        ts_ms=1000,
    )
    no = Book(
        token_id="no-fat-bids",
        bids=[Level(price=d("0.41"), size=d("500"))],
        asks=[Level(price=d("0.42"), size=d("3"))],
        tick=d("0.01"),
        min_order_size=d("5"),
        ts_ms=1000,
    )
    assert hunt(yes, no, MIN_EDGE, d("5"), d("500"), now_ms=1000) is None
    source = inspect.getsource(hunt)
    assert ".bids" not in source


def test_hunt_never_uses_float() -> None:
    hints = get_type_hints(hunt)
    for name, annotation in hints.items():
        assert not _type_includes_float(annotation), (
            f"hunt annotation {name} must not include float"
        )
    tree = ast.parse(inspect.getsource(hunt))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float"
        if isinstance(node, ast.Constant) and type(node.value) is float:
            raise AssertionError("hunt must not use float literals")
