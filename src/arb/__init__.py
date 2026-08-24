"""Paper-first Polymarket completeness-arb package."""

from arb.config import Settings, live_allowed, load_settings
from arb.money import D, d, round_price, round_size

__all__ = [
    "D",
    "Settings",
    "d",
    "live_allowed",
    "load_settings",
    "round_price",
    "round_size",
]
