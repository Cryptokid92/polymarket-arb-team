"""Task 2 contracts: protocol taker fee math. Maker rebates are excluded from EV."""

from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from typing import get_args, get_origin, get_type_hints

from arb.fees import (
    maker_fee,
    net_edge_maker,
    net_edge_taker,
    pair_taker_fees,
    taker_fee,
)
from arb.money import d


def _type_includes_float(annotation: object) -> bool:
    origin = get_origin(annotation)
    if annotation is float:
        return True
    if origin is None:
        return annotation is float
    return any(arg is float for arg in get_args(annotation))


def test_crypto_100_shares_at_fifty_cents_is_1_75() -> None:
    assert taker_fee(d("100"), d("0.50"), d("0.07")) == Decimal("1.75")


def test_crypto_100_shares_at_one_cent_matches_official_table() -> None:
    raw = d("100") * d("0.07") * d("0.01") * (d("1") - d("0.01"))
    assert raw == Decimal("0.0693")
    # Official 100-share crypto table lists this row as $0.07.
    assert taker_fee(d("100"), d("0.01"), d("0.07")) == Decimal("0.07")


def test_maker_fee_is_always_zero() -> None:
    assert maker_fee(d("100"), d("0.50"), d("0.07")) == Decimal("0")
    assert maker_fee(d("100"), d("0.01"), d("0.07")) == Decimal("0")


def test_net_edge_maker_excludes_rebate() -> None:
    # 3¢ on 100 shares is $3.00. A 20% crypto maker rebate must not be added.
    assert net_edge_maker(d("0.03"), d("100")) == Decimal("3.00")
    assert net_edge_maker(d("0.03"), d("100")) != Decimal("3.60")


def test_three_cent_taker_edge_is_negative_after_two_crypto_peak_fees() -> None:
    fees = pair_taker_fees(
        d("100"),
        d("0.50"),
        d("100"),
        d("0.50"),
        d("0.07"),
        d("0.07"),
    )
    assert fees == Decimal("3.50")
    net = net_edge_taker(d("0.03"), d("100"), fees)
    assert net == Decimal("-0.50")
    assert net < Decimal("0")


def test_geopolitics_fee_rate_zero_means_taker_fees_zero() -> None:
    assert taker_fee(d("100"), d("0.50"), d("0")) == Decimal("0")
    assert pair_taker_fees(
        d("100"),
        d("0.50"),
        d("100"),
        d("0.50"),
        d("0"),
        d("0"),
    ) == Decimal("0")


def test_fee_public_helpers_never_use_float() -> None:
    public_helpers = (
        taker_fee,
        pair_taker_fees,
        net_edge_taker,
        net_edge_maker,
        maker_fee,
    )
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
