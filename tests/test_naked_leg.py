"""Task 8 contracts: paper hedge flattens leftover naked legs."""

from __future__ import annotations

import ast
import inspect
import textwrap
from decimal import Decimal

from arb.money import d
from arb.naked_leg import Hedge, after_timeout_hedge, hedge_plan, naked_delta


def _assert_no_network(source: str) -> None:
    lowered = source.lower()
    assert "asyncsecureclient" not in lowered
    assert "from polymarket" not in source
    assert "http" not in lowered
    assert "websocket" not in lowered
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "AsyncSecureClient"


def test_naked_delta_and_timeout_sells_excess_yes() -> None:
    assert naked_delta(d("10"), d("0")) == Decimal("10")
    plan = after_timeout_hedge(d("10"), d("0"), timed_out=True)
    assert isinstance(plan, Hedge)
    assert plan.side == "YES"
    assert plan.action == "SELL_FAK"
    assert plan.size == Decimal("10")
    assert plan.incident is True
    assert after_timeout_hedge(d("10"), d("0"), timed_out=False) is None


def test_balanced_fills_have_no_hedge() -> None:
    assert naked_delta(d("10"), d("10")) == Decimal("0")
    assert hedge_plan(d("10"), d("10")) is None
    assert after_timeout_hedge(d("10"), d("10"), timed_out=True) is None


def test_timeout_sells_excess_no() -> None:
    plan = hedge_plan(d("3"), d("8"))
    assert plan is not None
    assert plan.side == "NO"
    assert plan.size == Decimal("5")
    assert plan.incident is True


def test_paper_hedge_has_no_network() -> None:
    import arb.naked_leg as hedge_mod

    _assert_no_network(inspect.getsource(hedge_mod))
    _assert_no_network(inspect.getsource(hedge_plan))
    _assert_no_network(inspect.getsource(after_timeout_hedge))
