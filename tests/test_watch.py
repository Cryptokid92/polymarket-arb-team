"""Hot watch pin + rotate. Does not raise WATCH_PAIRS."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from arb.app import PIN_HOT_PAIRS, WATCH_PAIRS, watch_slice
from arb.money import d
from arb.watch import hot_watch_slice, pair_score, watch_board_rows


def _pairs(n: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(condition_id=f"c{i}", i=i) for i in range(n)]


def test_no_scores_matches_plain_watch_slice() -> None:
    pairs = _pairs(12)
    plain = watch_slice(pairs, 0, 8)
    hot = hot_watch_slice(
        pairs,
        0,
        8,
        {},
        pin_n=3,
        condition_id_of=lambda p: p.condition_id,
        rotate_slice=watch_slice,
    )
    assert [p.condition_id for p in hot] == [p.condition_id for p in plain]


def test_pins_highest_edge_then_rotates_rest() -> None:
    pairs = _pairs(6)
    scores = {"c5": d("0.02"), "c1": d("0.01"), "c0": d("-0.04")}
    hot = hot_watch_slice(
        pairs,
        offset=0,
        watch_pairs=4,
        scores=scores,
        pin_n=2,
        condition_id_of=lambda p: p.condition_id,
        rotate_slice=watch_slice,
    )
    ids = [p.condition_id for p in hot]
    assert ids[:2] == ["c5", "c1"]
    assert "c5" in ids and "c1" in ids
    assert len(ids) == 4
    assert len(set(ids)) == 4


def test_pin_leaves_rotate_room_when_universe_exceeds_watch() -> None:
    pairs = _pairs(4)
    hot = hot_watch_slice(
        pairs,
        0,
        2,
        {"c0": d("0.02"), "c1": d("0.01")},
        pin_n=8,
        condition_id_of=lambda p: p.condition_id,
        rotate_slice=watch_slice,
    )
    assert len(hot) == 2
    assert hot[0].condition_id == "c0"
    second = hot_watch_slice(
        pairs,
        1,
        2,
        {"c0": d("0.02"), "c1": d("0.01")},
        pin_n=8,
        condition_id_of=lambda p: p.condition_id,
        rotate_slice=watch_slice,
    )
    assert [p.condition_id for p in hot] != [p.condition_id for p in second]


def test_pin_hot_pairs_stays_inside_watch_cap() -> None:
    assert PIN_HOT_PAIRS == 8
    assert PIN_HOT_PAIRS <= WATCH_PAIRS
    pairs = _pairs(100)
    scores = {f"c{i}": d("0.01") for i in range(20)}
    hot = hot_watch_slice(
        pairs,
        10,
        WATCH_PAIRS,
        scores,
        pin_n=PIN_HOT_PAIRS,
        condition_id_of=lambda p: p.condition_id,
        rotate_slice=watch_slice,
    )
    assert len(hot) == WATCH_PAIRS


def test_pair_score_missing_is_worst() -> None:
    assert pair_score({}, "x") == Decimal("-1")
    assert pair_score({"x": d("0.02")}, "x") == Decimal("0.02")


def test_watch_board_rows_marks_pins_and_edges() -> None:
    pairs = _pairs(3)
    rows = watch_board_rows(
        pairs,
        {"c0": d("0.02"), "c2": d("-0.01")},
        pinned_n=1,
        condition_id_of=lambda item: item.condition_id,
        label_of=lambda item: f"q-{item.condition_id}",
    )
    assert rows[0] == {
        "condition_id": "c0",
        "label": "q-c0",
        "pinned": True,
        "raw_edge": "0.02",
    }
    assert rows[1]["pinned"] is False
    assert rows[1]["raw_edge"] is None
    assert rows[2]["raw_edge"] == "-0.01"
