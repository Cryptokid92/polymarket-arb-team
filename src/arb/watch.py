"""Watch-slice helpers. Do not raise WATCH_PAIRS or LIST_SAFETY_CAP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import TypeVar

from arb.books import _reject_float

T = TypeVar("T")
_MISSING = Decimal("-1")


def pair_score(scores: Mapping[str, Decimal], condition_id: str) -> Decimal:
    raw = scores.get(condition_id)
    if raw is None:
        return _MISSING
    return _reject_float(raw, "watch_score")


def hot_watch_slice(
    pairs: Sequence[T],
    offset: int,
    watch_pairs: int,
    scores: Mapping[str, Decimal],
    *,
    pin_n: int,
    condition_id_of,
    rotate_slice,
) -> list[T]:
    """Pin the highest-edge pairs; rotate the rest. Total length <= watch_pairs.

    `condition_id_of(pair) -> str`. `rotate_slice` is watch_slice(items, offset, n).
    Missing scores sort last (original order among ties).
    """
    if not pairs or watch_pairs <= 0:
        return []
    watch_n = min(int(watch_pairs), len(pairs))
    pinned_n = min(max(0, int(pin_n)), watch_n, len(pairs))
    # Always leave a rotate slot when the universe is larger than the watch.
    if len(pairs) > watch_n:
        pinned_n = min(pinned_n, max(0, watch_n - 1))
    ranked = [
        pair
        for _idx, pair in sorted(
            enumerate(pairs),
            key=lambda item: (
                -pair_score(scores, condition_id_of(item[1])),
                item[0],
            ),
        )
    ]
    pinned = ranked[:pinned_n]
    pinned_ids = {condition_id_of(pair) for pair in pinned}
    rest = [pair for pair in pairs if condition_id_of(pair) not in pinned_ids]
    rotate_n = watch_n - len(pinned)
    rotating = rotate_slice(rest, offset, rotate_n) if rest and rotate_n > 0 else []
    return list(pinned) + list(rotating)


def watch_board_rows(
    watched: Sequence[T],
    scores: Mapping[str, Decimal],
    *,
    pinned_n: int,
    condition_id_of,
    label_of,
) -> list[dict[str, object]]:
    """Snapshot of the current watch slice for the paper UI. Not a trade."""
    pin = max(0, int(pinned_n))
    rows: list[dict[str, object]] = []
    for index, item in enumerate(watched):
        cid = str(condition_id_of(item))
        raw = scores.get(cid)
        edge = None
        if raw is not None and raw != _MISSING:
            edge = str(_reject_float(raw, "watch_score"))
        label = str(label_of(item) or cid)
        rows.append(
            {
                "condition_id": cid,
                "label": label,
                "pinned": index < pin,
                "raw_edge": edge,
            }
        )
    return rows
