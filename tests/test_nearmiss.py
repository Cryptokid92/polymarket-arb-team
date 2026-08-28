"""Near-miss telemetry. Hunt still silent below min_edge. Caps stay tight."""

from __future__ import annotations

import ast
import inspect
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from arb.app import (
    BOOK_BATCH_SIZE,
    LIST_SAFETY_CAP,
    PIN_HOT_PAIRS,
    WATCH_PAIRS,
    run_pipeline_traced,
)
from arb.books import BookStore
from arb.config import Settings, _EnvSettings
from arb.fee_agent import MarketFees
from arb.hunter import hunt
from arb.money import d
from arb.nearmiss import (
    NearMissTracker,
    edge_bucket,
    measure_pair,
    should_log_nearmiss,
)
from arb.risk import MarketFlags, Portfolio

FIXTURES = Path(__file__).parent / "fixtures" / "books"
MIN_EDGE = d("0.01")


def _type_includes_float(annotation: object) -> bool:
    origin = get_origin(annotation)
    if annotation is float:
        return True
    if origin is None:
        return annotation is float
    return any(arg is float for arg in get_args(annotation))


def _load_pair(name: str):
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    store = BookStore()
    yes = store.apply_snapshot(payload["yes"])
    no = store.apply_snapshot(payload["no"])
    return yes, no, payload


def test_no_gap_is_walked_near_miss_not_a_hunt_hit() -> None:
    yes, no, payload = _load_pair("no_gap.json")
    found = hunt(yes, no, MIN_EDGE, yes.min_order_size, d(payload["max_shares"]), now_ms=1000)
    assert found is None
    miss = measure_pair(
        yes,
        no,
        yes.min_order_size,
        d(payload["max_shares"]),
        1000,
        condition_id="c-no-gap",
        in_watch=True,
    )
    assert miss.thin is False
    assert miss.fillable_shares == Decimal("50")
    assert miss.yes_vwap == Decimal("0.50")
    assert miss.no_vwap == Decimal("0.50")
    assert miss.raw_edge == Decimal("0")
    assert miss.in_watch is True


def test_gap_3c_is_still_a_hunt_hit_and_best_edge() -> None:
    yes, no, payload = _load_pair("gap_3c.json")
    found = hunt(yes, no, MIN_EDGE, yes.min_order_size, d(payload["max_shares"]), now_ms=1000)
    assert found is not None
    assert found.raw_edge == Decimal("0.03")
    miss = measure_pair(
        yes,
        no,
        yes.min_order_size,
        d(payload["max_shares"]),
        1000,
        condition_id="c-gap",
        in_watch=False,
    )
    assert miss.raw_edge == Decimal("0.03")
    assert miss.fillable_shares == Decimal("80")
    assert miss.in_watch is False


def test_thin_depth_has_no_walked_edge() -> None:
    yes, no, payload = _load_pair("thin_depth.json")
    miss = measure_pair(
        yes,
        no,
        yes.min_order_size,
        d(payload["max_shares"]),
        1000,
        condition_id="c-thin",
        in_watch=True,
    )
    assert miss.thin is True
    assert miss.fillable_shares == Decimal("0")
    assert miss.raw_edge is None
    assert hunt(yes, no, MIN_EDGE, yes.min_order_size, d(payload["max_shares"]), now_ms=1000) is None


def test_tracker_best_ignores_thin_and_logs_nonnegative() -> None:
    yes_flat, no_flat, payload_flat = _load_pair("no_gap.json")
    yes_gap, no_gap, payload_gap = _load_pair("gap_3c.json")
    yes_thin, no_thin, payload_thin = _load_pair("thin_depth.json")
    tracker = NearMissTracker(top_n=5)
    thin = measure_pair(
        yes_thin,
        no_thin,
        yes_thin.min_order_size,
        d(payload_thin["max_shares"]),
        1000,
        condition_id="thin",
        in_watch=True,
    )
    assert tracker.observe(thin) is False
    assert tracker.best is None
    flat = measure_pair(
        yes_flat,
        no_flat,
        yes_flat.min_order_size,
        d(payload_flat["max_shares"]),
        1000,
        condition_id="flat",
        in_watch=True,
    )
    assert tracker.observe(flat) is True
    assert tracker.best is not None
    assert tracker.best.raw_edge == Decimal("0")
    gap = measure_pair(
        yes_gap,
        no_gap,
        yes_gap.min_order_size,
        d(payload_gap["max_shares"]),
        1000,
        condition_id="gap",
        in_watch=False,
    )
    assert tracker.observe(gap) is True
    assert tracker.best is not None
    assert tracker.best.condition_id == "gap"
    assert tracker.best.raw_edge == Decimal("0.03")
    snap = tracker.snapshot()
    assert snap["best_edge"] == "0.03"
    assert snap["closest_condition_id"] == "gap"
    assert snap["nearmiss_considers"] == 3
    assert snap["edge_histogram"]["none"] == 1
    assert snap["edge_histogram"]["0_0.005"] == 1
    assert snap["edge_histogram"]["gte_0.02"] == 1
    assert snap["edge_thresholds"]["gt_-0.005"] == 2
    assert snap["edge_thresholds"]["gt_0"] == 1
    assert snap["edge_thresholds"]["gte_0.01"] == 1
    assert snap["max_edge_window"] == "0.03"


def test_edge_bucket_and_log_rule() -> None:
    assert edge_bucket(None) == "none"
    assert edge_bucket(d("-0.06")) == "lt_-0.05"
    assert edge_bucket(d("-0.015")) == "-0.02_-0.01"
    assert edge_bucket(d("0")) == "0_0.005"
    assert edge_bucket(d("0.009")) == "0.005_0.01"
    assert edge_bucket(d("0.03")) == "gte_0.02"
    miss = measure_pair(
        *_load_pair("no_gap.json")[:2],
        d("5"),
        d("50"),
        1000,
        condition_id="x",
        in_watch=True,
    )
    assert should_log_nearmiss(miss, is_new_best=False) is True


def test_tracker_thresholds_and_window_max_reset() -> None:
    yes_flat, no_flat, payload_flat = _load_pair("no_gap.json")
    tracker = NearMissTracker()
    tracker.set_window(2)
    miss = measure_pair(
        yes_flat,
        no_flat,
        yes_flat.min_order_size,
        d(payload_flat["max_shares"]),
        1000,
        condition_id="flat",
        in_watch=True,
        window_id=2,
    )
    assert miss.window_id == 2
    tracker.observe(miss)
    assert tracker.window_id == 2
    assert tracker.max_edge_window == Decimal("0")
    assert tracker.threshold_counts["gt_-0.005"] == 1
    assert tracker.threshold_counts["gt_0"] == 0
    assert tracker.threshold_counts["gte_0.01"] == 0
    tracker.set_window(3)
    assert tracker.max_edge_window is None
    assert tracker.window_id == 3


def test_pipeline_trace_includes_near_miss_when_hunt_is_silent() -> None:
    yes, no, _payload = _load_pair("no_gap.json")
    settings = Settings(
        arb_mode="paper",
        max_notional_per_trade=d("25"),
        max_daily_loss=d("50"),
        max_open_pairs=3,
        min_edge=d("0.01"),
        max_gap=d("0.08"),
        stale_ms=400,
        hedge_timeout_ms=1500,
        ws_stale_ms=3000,
    )
    flags = MarketFlags(
        accepting_orders=True, seconds_delay=0, neg_risk=False, binary=True
    )
    portfolio = Portfolio(yes={}, no={}, open_pairs=0, daily_pnl=d("0"), halted=False)
    trace = run_pipeline_traced(
        yes, no, settings, flags, MarketFees(yes_rate=d("0"), no_rate=d("0")), portfolio, 1000
    )
    assert hunt(yes, no, MIN_EDGE, yes.min_order_size, d("50"), now_ms=1000) is None
    assert trace.near_miss is not None
    assert trace.near_miss.raw_edge == Decimal("0")
    assert trace.source == "maker"
    assert trace.gap is not None
    assert trace.intent is not None
    assert trace.intent.path == "maker_gtc"


def test_nearmiss_does_not_loosen_caps() -> None:
    fields = _EnvSettings.model_fields
    assert fields["stale_ms"].default == 400
    assert fields["min_edge"].default == Decimal("0.01")
    assert fields["max_gap"].default == Decimal("0.08")
    assert fields["max_notional_per_trade"].default == Decimal("25")
    assert LIST_SAFETY_CAP == 5000
    assert BOOK_BATCH_SIZE == 50
    assert WATCH_PAIRS == 100
    assert PIN_HOT_PAIRS <= WATCH_PAIRS
    assert PIN_HOT_PAIRS == 8


def test_nearmiss_never_uses_float() -> None:
    for fn in (measure_pair, edge_bucket):
        hints = get_type_hints(fn)
        for name, annotation in hints.items():
            assert not _type_includes_float(annotation), name
        tree = ast.parse(inspect.getsource(fn))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "float"
            if isinstance(node, ast.Constant) and type(node.value) is float:
                raise AssertionError("near-miss must not use float literals")
