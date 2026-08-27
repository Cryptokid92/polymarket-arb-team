"""Closest-book / near-miss telemetry. Does not emit gaps. Does not loosen hunt."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from arb.books import Book, _reject_float, fillable_pair_size, walk_asks

_ONE = Decimal("1")
_ZERO = Decimal("0")
_NEG_ONE = Decimal("-1")

# Walked-edge buckets only. Thin books (no fillable size) use "none".
_BUCKETS: tuple[tuple[Decimal | None, str], ...] = (
    (Decimal("-0.05"), "lt_-0.05"),
    (Decimal("-0.02"), "-0.05_-0.02"),
    (Decimal("-0.01"), "-0.02_-0.01"),
    (_ZERO, "-0.01_0"),
    (Decimal("0.005"), "0_0.005"),
    (Decimal("0.01"), "0.005_0.01"),
    (Decimal("0.02"), "0.01_0.02"),
    (None, "gte_0.02"),
)


class NearMiss(BaseModel):
    """Diagnostic walk of YES+NO asks. Never a trade signal by itself."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    condition_id: str
    yes_token_id: str
    no_token_id: str
    fillable_shares: Decimal
    yes_vwap: Decimal | None
    no_vwap: Decimal | None
    raw_edge: Decimal | None
    book_age_ms: int
    in_watch: bool
    thin: bool

    @field_validator("fillable_shares", mode="before")
    @classmethod
    def _size_decimal(cls, value: object) -> Decimal:
        return _reject_float(value, "fillable_shares")

    @field_validator("yes_vwap", "no_vwap", "raw_edge", mode="before")
    @classmethod
    def _optional_decimal(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _reject_float(value, "near_miss")


def measure_pair(
    yes: Book,
    no: Book,
    min_size: Decimal,
    max_shares: Decimal,
    now_ms: int,
    *,
    condition_id: str,
    in_watch: bool,
) -> NearMiss:
    """Walk ask depth. raw_edge is set only when both sides fill min_size."""
    min_size = _reject_float(min_size, "min_size")
    max_shares = _reject_float(max_shares, "max_shares")
    older_ts = yes.ts_ms if yes.ts_ms < no.ts_ms else no.ts_ms
    fillable = fillable_pair_size(yes.asks, no.asks, min_size, max_shares)
    if fillable < min_size:
        return NearMiss(
            condition_id=condition_id,
            yes_token_id=yes.token_id,
            no_token_id=no.token_id,
            fillable_shares=_ZERO,
            yes_vwap=None,
            no_vwap=None,
            raw_edge=None,
            book_age_ms=now_ms - older_ts,
            in_watch=in_watch,
            thin=True,
        )
    yes_walk = walk_asks(yes.asks, fillable)
    no_walk = walk_asks(no.asks, fillable)
    if yes_walk is None or no_walk is None:
        return NearMiss(
            condition_id=condition_id,
            yes_token_id=yes.token_id,
            no_token_id=no.token_id,
            fillable_shares=_ZERO,
            yes_vwap=None,
            no_vwap=None,
            raw_edge=None,
            book_age_ms=now_ms - older_ts,
            in_watch=in_watch,
            thin=True,
        )
    yes_vwap, _yes = yes_walk
    no_vwap, _no = no_walk
    raw_edge = _ONE - yes_vwap - no_vwap
    return NearMiss(
        condition_id=condition_id,
        yes_token_id=yes.token_id,
        no_token_id=no.token_id,
        fillable_shares=fillable,
        yes_vwap=yes_vwap,
        no_vwap=no_vwap,
        raw_edge=raw_edge,
        book_age_ms=now_ms - older_ts,
        in_watch=in_watch,
        thin=False,
    )


def edge_bucket(raw_edge: Decimal | None) -> str:
    if raw_edge is None:
        return "none"
    raw_edge = _reject_float(raw_edge, "raw_edge")
    for bound, name in _BUCKETS:
        if bound is None:
            return name
        if raw_edge < bound:
            return name
    return "gte_0.02"


def should_log_nearmiss(miss: NearMiss, *, is_new_best: bool) -> bool:
    """JSONL only for a new best or a walked non-negative edge. Avoid flood."""
    if is_new_best:
        return True
    if miss.raw_edge is None:
        return False
    return miss.raw_edge >= _ZERO


class NearMissTracker:
    """Rolling best + histogram. Does not change hunt/risk caps."""

    def __init__(self, top_n: int = 20) -> None:
        self.top_n = int(top_n)
        self.best: NearMiss | None = None
        self.top: list[NearMiss] = []
        self.histogram: dict[str, int] = {}
        self.considers: int = 0
        self.thin: int = 0

    def observe(self, miss: NearMiss) -> bool:
        self.considers += 1
        if miss.thin:
            self.thin += 1
        bucket = edge_bucket(miss.raw_edge)
        self.histogram[bucket] = self.histogram.get(bucket, 0) + 1
        is_new_best = False
        if miss.raw_edge is not None:
            if self.best is None or self.best.raw_edge is None:
                self.best = miss
                is_new_best = True
            elif miss.raw_edge > self.best.raw_edge:
                self.best = miss
                is_new_best = True
        self._remember_top(miss)
        return should_log_nearmiss(miss, is_new_best=is_new_best)

    def _remember_top(self, miss: NearMiss) -> None:
        if miss.raw_edge is None:
            return
        self.top.append(miss)
        self.top.sort(
            key=lambda row: row.raw_edge if row.raw_edge is not None else _NEG_ONE,
            reverse=True,
        )
        if len(self.top) > self.top_n:
            self.top = self.top[: self.top_n]

    def snapshot(self) -> dict[str, object]:
        best = self.best
        return {
            "best_edge": str(best.raw_edge) if best is not None and best.raw_edge is not None else None,
            "closest_condition_id": best.condition_id if best is not None else None,
            "closest_fillable": str(best.fillable_shares) if best is not None else None,
            "closest_book_age_ms": best.book_age_ms if best is not None else None,
            "closest_in_watch": best.in_watch if best is not None else None,
            "closest_thin": best.thin if best is not None else None,
            "nearmiss_considers": self.considers,
            "edge_histogram": dict(self.histogram),
        }
