"""Task 8 contracts: paper merge never touches the network."""

from __future__ import annotations

import ast
import inspect
import textwrap
from decimal import Decimal

import pytest

from arb.merge import maybe_merge, mergeable
from arb.money import d


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


def test_mergeable_is_the_min() -> None:
    assert mergeable(d("10"), d("7")) == Decimal("7")
    assert mergeable(d("7"), d("10")) == Decimal("7")
    assert mergeable(d("0"), d("5")) == Decimal("0")


@pytest.mark.asyncio
async def test_maybe_merge_paper_returns_qty_without_client() -> None:
    qty = await maybe_merge(
        client=object(),
        condition_id="cond-paper",
        yes_shares=d("10"),
        no_shares=d("7"),
        mode="paper",
    )
    assert qty == Decimal("7")
    _assert_no_network(inspect.getsource(maybe_merge))
    _assert_no_network(inspect.getsource(mergeable))


@pytest.mark.asyncio
async def test_maybe_merge_zero_when_nothing_to_merge() -> None:
    qty = await maybe_merge(object(), "cond", d("0"), d("4"), mode="paper")
    assert qty == Decimal("0")


@pytest.mark.asyncio
async def test_maybe_merge_live_raises_without_network() -> None:
    with pytest.raises(RuntimeError, match="Task 12"):
        await maybe_merge(object(), "cond", d("10"), d("7"), mode="live")


def test_merge_module_has_no_network() -> None:
    import arb.merge as merge_mod

    _assert_no_network(inspect.getsource(merge_mod))
