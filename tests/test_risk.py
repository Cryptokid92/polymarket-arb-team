"""Task 5 contracts: risk agent refuses uncompletable and delayed markets."""

from __future__ import annotations

import ast
import inspect
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from arb.books import BookStore, Level
from arb.config import Settings
from arb.hunter import hunt
from arb.messages import GapFound
from arb.money import d
from arb.risk import MarketFlags, Portfolio, approve

FIXTURES = Path(__file__).parent / "fixtures" / "books"
MIN_EDGE = d("0.01")


def _type_includes_float(annotation: object) -> bool:
    origin = get_origin(annotation)
    if annotation is float:
        return True
    if origin is None:
        return annotation is float
    return any(arg is float for arg in get_args(annotation))


def _settings(**overrides: Any) -> Settings:
    base = dict(
        max_notional_per_trade=d("25"),
        max_daily_loss=d("50"),
        max_open_pairs=3,
        min_edge=d("0.01"),
        max_gap=d("0.08"),
        stale_ms=400,
        hedge_timeout_ms=1500,
        ws_stale_ms=3000,
    )
    base.update(overrides)
    return Settings(**base)


def _flags(**overrides: Any) -> MarketFlags:
    base = dict(accepting_orders=True, seconds_delay=0, neg_risk=False, binary=True)
    base.update(overrides)
    return MarketFlags(**base)


def _portfolio(**overrides: Any) -> Portfolio:
    base: dict[str, Any] = dict(
        yes={},
        no={},
        open_pairs=0,
        daily_pnl=d("0"),
        halted=False,
    )
    base.update(overrides)
    return Portfolio(**base)


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


def test_approve_gap_3c_healthy_empty_portfolio() -> None:
    gap = _gap_3c()
    approved = approve(gap, _portfolio(), _settings(), _flags())
    assert approved is not None
    pair_px = approved.yes_vwap + approved.no_vwap
    assert approved.fillable_shares * pair_px <= d("25")
    assert approved.fillable_shares > 0
    assert approved.raw_edge == Decimal("1") - approved.yes_vwap - approved.no_vwap


def test_reject_halted() -> None:
    assert approve(_gap_3c(), _portfolio(halted=True), _settings(), _flags()) is None


def test_reject_not_binary() -> None:
    assert approve(_gap_3c(), _portfolio(), _settings(), _flags(binary=False)) is None


def test_reject_not_accepting_orders() -> None:
    assert (
        approve(_gap_3c(), _portfolio(), _settings(), _flags(accepting_orders=False))
        is None
    )


def test_reject_seconds_delay_uses_delayed_market() -> None:
    yes, no, payload = _load_pair("delayed_market.json")
    found = hunt(yes, no, MIN_EDGE, yes.min_order_size, d("20"), now_ms=int(yes.ts_ms))
    assert found is not None
    assert found.book_age_ms == 0
    assert payload["market_ts_ms"] < yes.ts_ms
    assert approve(found, _portfolio(), _settings(), _flags(seconds_delay=3)) is None


def test_reject_neg_risk() -> None:
    assert approve(_gap_3c(), _portfolio(), _settings(), _flags(neg_risk=True)) is None


def test_reject_stale_one_side_book_age() -> None:
    yes, no, payload = _load_pair("stale_one_side.json")
    now_ms = int(payload["now_ms"])
    found = hunt(yes, no, MIN_EDGE, yes.min_order_size, d("20"), now_ms=now_ms)
    assert found is not None
    assert found.book_age_ms > _settings().stale_ms
    assert approve(found, _portfolio(), _settings(), _flags()) is None


def test_reject_raw_edge_above_max_gap() -> None:
    assert approve(_gap_3c(), _portfolio(), _settings(max_gap=d("0.02")), _flags()) is None


def test_reject_max_open_pairs() -> None:
    assert approve(_gap_3c(), _portfolio(open_pairs=3), _settings(), _flags()) is None


def test_reject_daily_loss() -> None:
    assert (
        approve(_gap_3c(), _portfolio(daily_pnl=d("-50")), _settings(), _flags()) is None
    )


def test_reject_uncompletable_walk() -> None:
    gap = _gap_3c().model_copy(
        update={
            "yes_asks": [Level(price=d("0.55"), size=d("3"))],
            "no_asks": [Level(price=d("0.42"), size=d("3"))],
            "fillable_shares": d("80"),
        }
    )
    assert approve(gap, _portfolio(), _settings(), _flags()) is None


def test_reject_notional_when_clip_is_zero() -> None:
    assert (
        approve(
            _gap_3c(),
            _portfolio(),
            _settings(max_notional_per_trade=d("0.001")),
            _flags(),
        )
        is None
    )


def test_approve_never_uses_float() -> None:
    hints = get_type_hints(approve)
    for name, annotation in hints.items():
        assert not _type_includes_float(annotation)
    tree = ast.parse(inspect.getsource(approve))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float"
        if isinstance(node, ast.Constant) and type(node.value) is float:
            raise AssertionError("approve must not use float literals")
