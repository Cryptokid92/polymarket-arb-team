"""Paper-first preflight. Live geoblock must be injected; default tests stay offline."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from arb.config import Settings

GeoblockFetcher = Callable[[], dict]


class PreflightResult(BaseModel):
    ok: bool
    reason: str | None = None


def _allow_live_is_today(project_root: Path) -> bool:
    path = project_root / "ALLOW_LIVE"
    if not path.is_file():
        return False
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return False
    return raw.splitlines()[0].strip() == date.today().isoformat()


def _caps_ok(settings: Settings) -> bool:
    return (
        settings.max_notional_per_trade > Decimal("0")
        and settings.max_daily_loss > Decimal("0")
        and settings.max_open_pairs > 0
        and settings.stale_ms > 0
        and settings.ws_stale_ms > 0
    )


def run_preflight(
    settings: Settings,
    project_root: Path,
    *,
    geoblock_fetcher: GeoblockFetcher | None = None,
) -> PreflightResult:
    if settings.arb_mode != "live":
        return PreflightResult(ok=True)

    if not _allow_live_is_today(project_root):
        return PreflightResult(ok=False, reason="ALLOW_LIVE missing or not today")
    if not settings.private_key or not settings.wallet_address:
        return PreflightResult(ok=False, reason="missing keys")
    if not _caps_ok(settings):
        return PreflightResult(ok=False, reason="invalid settings caps")
    if geoblock_fetcher is None:
        return PreflightResult(ok=False, reason="geoblock fetcher required for live")
    geo = geoblock_fetcher()
    if geo.get("blocked") is True:
        return PreflightResult(ok=False, reason="geoblocked")
    return PreflightResult(ok=True)
