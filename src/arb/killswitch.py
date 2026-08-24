"""Manual-resume kill switch. Never auto-resumes after halt."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from arb.config import Settings
from arb.state import StateStore

_HOUR_MS = 3_600_000


class KillSwitch:
    def __init__(
        self,
        project_root: Path,
        state: StateStore,
        settings: Settings,
    ) -> None:
        self.project_root = Path(project_root)
        self.state = state
        self.settings = settings

    def trip(self, reason: str) -> None:
        self.state.set_halted(True)

    def allow_new_intents(self) -> bool:
        if (self.project_root / "HALT").is_file():
            return False
        return not self.state.restore().halted

    def resume(self) -> bool:
        """Human-only. Refuses if HALT is still present. Never called by evaluate()."""
        if (self.project_root / "HALT").is_file():
            return False
        self.state.set_halted(False)
        return True

    def evaluate(
        self,
        *,
        daily_pnl: Decimal,
        ws_age_ms: int,
        now_ms: int,
        unrealized: Decimal | None = None,
    ) -> bool:
        realized_and_unrealized = daily_pnl + (
            unrealized if unrealized is not None else Decimal("0")
        )
        if realized_and_unrealized <= -self.settings.max_daily_loss:
            self.trip("daily_loss")
        if (self.project_root / "HALT").is_file():
            self.trip("halt_file")
        if ws_age_ms > self.settings.ws_stale_ms:
            self.trip("ws_stale")
        if self.state.hedge_incidents_since(now_ms - _HOUR_MS) >= 3:
            self.trip("hedge_incidents")
        return self.allow_new_intents()
