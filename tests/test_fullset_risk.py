"""Approve neg-risk full-set gaps. Decimal only. Paper only."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from arb.config import Settings
from arb.fullset_risk import FullSetGap, approve_full_set
from arb.money import d


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


def _gap(**overrides: Any) -> FullSetGap:
    base: dict[str, Any] = dict(
        event_id="evt-3way",
        token_ids=("yes-a", "yes-b", "yes-c"),
        fillable_shares=d("5"),
        vwaps=(d("0.40"), d("0.30"), d("0.28")),
        raw_edge=d("0.02"),
        ts_ms=2000,
        book_age_ms=0,
    )
    base.update(overrides)
    return FullSetGap(**base)


def test_stale_gap_refused() -> None:
    gap = _gap(book_age_ms=401)
    assert approve_full_set(gap, _settings(), now_ms=2000) is None


def test_edge_above_max_gap_refused() -> None:
    gap = _gap(raw_edge=d("0.20"))
    assert approve_full_set(gap, _settings(max_gap=d("0.08")), now_ms=2000) is None


def test_good_two_cent_edge_approved() -> None:
    gap = _gap(raw_edge=d("0.02"))
    approved = approve_full_set(gap, _settings(), now_ms=2000)
    assert approved is not None
    assert approved.raw_edge == Decimal("0.02")
    assert approved.fillable_shares == Decimal("5")
    assert approved.event_id == "evt-3way"
