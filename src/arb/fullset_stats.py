"""Paper full-set run stats payload. Decimal-only; no live orders."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class FullSetRunStats:
    fullset_events: int = 0
    fullset_gaps: int = 0
    fullset_fills: int = 0
    closest_set_sum: Decimal | None = None


def fullset_stats_payload(stats: FullSetRunStats) -> dict[str, object]:
    return {
        "fullset_events": stats.fullset_events,
        "fullset_gaps": stats.fullset_gaps,
        "fullset_fills": stats.fullset_fills,
        "closest_set_sum": str(stats.closest_set_sum) if stats.closest_set_sum is not None else None,
    }
