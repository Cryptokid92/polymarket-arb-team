"""Paper-only local alerts when an intent is chosen. No network. No live client."""

from __future__ import annotations

from typing import Any

from arb.messages import Intent


def alert_record(
    intent: Intent,
    now_ms: int,
    *,
    outcome: str | None = None,
) -> dict[str, Any]:
    """JSONL row for the local dashboard. Not a live order."""
    return {
        "ts_ms": now_ms,
        "condition_id": intent.gap.condition_id,
        "path": intent.path,
        "size": str(intent.size),
        "yes_vwap": str(intent.gap.yes_vwap),
        "no_vwap": str(intent.gap.no_vwap),
        "raw_edge": str(intent.gap.raw_edge),
        "expected_net_edge": str(intent.expected_net_edge),
        "yes_limit": str(intent.yes_limit),
        "no_limit": str(intent.no_limit),
        "outcome": outcome,
    }
