"""Paper-default settings and the dual live-trading gate."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseModel):
    arb_mode: Literal["paper", "live"] = "paper"
    max_notional_per_trade: Decimal
    max_daily_loss: Decimal
    max_open_pairs: int
    min_edge: Decimal
    max_gap: Decimal
    stale_ms: int
    hedge_timeout_ms: int
    ws_stale_ms: int
    private_key: str | None = None
    wallet_address: str | None = None


class _EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    arb_mode: Literal["paper", "live"] = Field(
        default="paper",
        validation_alias=AliasChoices("ARB_MODE", "arb_mode"),
    )
    max_notional_per_trade: Decimal = Field(
        default=Decimal("25"),
        validation_alias=AliasChoices(
            "MAX_NOTIONAL_PER_TRADE_PUSD",
            "max_notional_per_trade",
        ),
    )
    max_daily_loss: Decimal = Field(
        default=Decimal("50"),
        validation_alias=AliasChoices("MAX_DAILY_LOSS_PUSD", "max_daily_loss"),
    )
    max_open_pairs: int = Field(
        default=3,
        validation_alias=AliasChoices("MAX_OPEN_PAIRS", "max_open_pairs"),
    )
    min_edge: Decimal = Field(
        default=Decimal("0.01"),
        validation_alias=AliasChoices("MIN_EDGE", "min_edge"),
    )
    max_gap: Decimal = Field(
        default=Decimal("0.08"),
        validation_alias=AliasChoices("MAX_GAP", "max_gap"),
    )
    stale_ms: int = Field(
        default=400,
        validation_alias=AliasChoices("STALE_MS", "stale_ms"),
    )
    hedge_timeout_ms: int = Field(
        default=1500,
        validation_alias=AliasChoices("HEDGE_TIMEOUT_MS", "hedge_timeout_ms"),
    )
    ws_stale_ms: int = Field(
        default=3000,
        validation_alias=AliasChoices("WS_STALE_MS", "ws_stale_ms"),
    )
    private_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("POLYMARKET_PRIVATE_KEY", "private_key"),
    )
    wallet_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("POLYMARKET_WALLET_ADDRESS", "wallet_address"),
    )

    @field_validator("private_key", "wallet_address", mode="before")
    @classmethod
    def _blank_secret_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value


def load_settings() -> Settings:
    env = _EnvSettings()
    return Settings.model_validate(env.model_dump())


def live_allowed(project_root: Path) -> bool:
    """True only if arb_mode=='live' AND ALLOW_LIVE file exists with today's date."""
    if load_settings().arb_mode != "live":
        return False
    allow_path = project_root / "ALLOW_LIVE"
    if not allow_path.is_file():
        return False
    raw = allow_path.read_text(encoding="utf-8").strip()
    if not raw:
        return False
    first_line = raw.splitlines()[0].strip()
    return first_line == date.today().isoformat()
