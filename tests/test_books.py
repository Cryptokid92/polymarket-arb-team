"""Task 3 contracts: reconstruct books and walk ask depth (not top-of-book)."""

from __future__ import annotations

import ast
import inspect
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from arb.books import BookStore, Level, fillable_pair_size, walk_asks
from arb.money import d

FIXTURES = Path(__file__).parent / "fixtures" / "books"


def _type_includes_float(annotation: object) -> bool:
    origin = get_origin(annotation)
    if annotation is float:
        return True
    if origin is None:
        return annotation is float
    return any(arg is float for arg in get_args(annotation))


def _load_pair(name: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return payload["yes"], payload["no"], payload


def test_gap_3c_fixture_exists() -> None:
    assert (FIXTURES / "gap_3c.json").is_file()
    assert (FIXTURES / "thin_depth.json").is_file()
    assert (FIXTURES / "no_gap.json").is_file()
    assert (FIXTURES / "stale_one_side.json").is_file()
    assert (FIXTURES / "delayed_market.json").is_file()


def test_gap_3c_fillable_80_and_vwap_sum_0_97() -> None:
    yes_raw, no_raw, payload = _load_pair("gap_3c.json")
    store = BookStore()
    yes = store.apply_snapshot(yes_raw)
    no = store.apply_snapshot(no_raw)
    size = fillable_pair_size(
        yes.asks,
        no.asks,
        yes.min_order_size,
        d(payload["max_shares"]),
    )
    assert size == Decimal("80")
    yes_walk = walk_asks(yes.asks, size)
    no_walk = walk_asks(no.asks, size)
    assert yes_walk is not None and no_walk is not None
    yes_vwap, yes_filled = yes_walk
    no_vwap, no_filled = no_walk
    assert yes_filled == Decimal("80")
    assert no_filled == Decimal("80")
    assert yes_vwap + no_vwap == Decimal("0.97")


def test_thin_depth_fillable_zero() -> None:
    yes_raw, no_raw, payload = _load_pair("thin_depth.json")
    store = BookStore()
    yes = store.apply_snapshot(yes_raw)
    no = store.apply_snapshot(no_raw)
    size = fillable_pair_size(
        yes.asks,
        no.asks,
        yes.min_order_size,
        d(payload["max_shares"]),
    )
    assert size == Decimal("0")
    assert yes.min_order_size == Decimal("5")
    yes_depth = sum((lvl.size for lvl in yes.asks), Decimal("0"))
    assert yes_depth < yes.min_order_size


def test_walk_asks_none_when_depth_insufficient() -> None:
    asks = [Level(price=d("0.55"), size=d("10"))]
    assert walk_asks(asks, d("11")) is None
    assert walk_asks([], d("5")) is None


def test_walk_asks_uses_full_depth_not_top_of_book() -> None:
    asks = [
        Level(price=d("0.55"), size=d("30")),
        Level(price=d("0.56"), size=d("50")),
    ]
    walked = walk_asks(asks, d("80"))
    assert walked is not None
    vwap, filled = walked
    assert filled == Decimal("80")
    assert vwap == Decimal("0.55625")
    top_only = fillable_pair_size(
        asks,
        [Level(price=d("0.42"), size=d("80"))],
        d("5"),
        d("80"),
    )
    assert top_only == Decimal("80")


def test_price_change_updates_size_ts_and_hash() -> None:
    yes_raw, no_raw, _ = _load_pair("gap_3c.json")
    store = BookStore()
    yes = store.apply_snapshot(yes_raw)
    store.apply_snapshot(no_raw)
    assert yes.ts_ms == 1000
    assert store.book_hash(yes.token_id) == "yes-gap-3c-v1"
    assert yes.asks[0].size == Decimal("80")

    updated = store.apply_price_change(
        {
            "timestamp": "2500",
            "price_changes": [
                {
                    "asset_id": yes.token_id,
                    "price": "0.55",
                    "size": "40",
                    "side": "SELL",
                    "hash": "yes-gap-3c-v2",
                }
            ],
        }
    )
    assert updated
    book = store.get(yes.token_id)
    assert book is not None
    assert book.ts_ms == 2500
    assert book.asks[0].size == Decimal("40")
    assert store.book_hash(yes.token_id) == "yes-gap-3c-v2"
    assert store.book_hash(yes.token_id) != "yes-gap-3c-v1"
    assert store.get(no_raw["token_id"]) is not None


def test_price_change_size_zero_removes_level() -> None:
    yes_raw, _, _ = _load_pair("gap_3c.json")
    store = BookStore()
    store.apply_snapshot(yes_raw)
    store.apply_price_change(
        {
            "timestamp": 3000,
            "price_changes": [
                {
                    "token_id": yes_raw["token_id"],
                    "price": "0.55",
                    "size": "0",
                    "side": "SELL",
                    "hash": "yes-gap-3c-empty",
                }
            ],
        }
    )
    book = store.get(yes_raw["token_id"])
    assert book is not None
    assert book.asks == []
    assert book.ts_ms == 3000
    assert store.book_hash(yes_raw["token_id"]) == "yes-gap-3c-empty"


def test_book_helpers_never_use_float() -> None:
    public_helpers = (walk_asks, fillable_pair_size)
    for helper in public_helpers:
        hints = get_type_hints(helper)
        for name, annotation in hints.items():
            assert not _type_includes_float(annotation), (
                f"{helper.__name__} annotation {name} must not include float"
            )
        source = inspect.getsource(helper)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "float", f"{helper.__name__} must not call float()"
            if isinstance(node, ast.Constant) and type(node.value) is float:
                raise AssertionError(f"{helper.__name__} must not use float literals")

    try:
        Level(price=0.55, size=80)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return
    raise AssertionError("Level must reject float prices")
