"""Paper pair poster and a live stub that refuses without the dual gate."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from arb.books import _reject_float
from arb.bus import Bus, Topic
from arb.config import live_allowed
from arb.messages import Intent

_DEFAULT_LOG = Path("data/paper/intents.jsonl")


class PaperOrder(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    order_id: str
    token_id: str
    outcome: Literal["YES", "NO"]
    side: Literal["BUY"]
    path: Literal["maker_gtc", "taker_fak"]
    size: Decimal
    limit: Decimal
    status: Literal["paper_posted"] = "paper_posted"

    @field_validator("size", "limit", mode="before")
    @classmethod
    def _decimal_only(cls, value: object) -> Decimal:
        return _reject_float(value, "paper_order")


class PaperFill(BaseModel):
    yes: PaperOrder
    no: PaperOrder


class PaperBroker:
    """Writes paper pair posts to JSONL. Never calls a secure client."""

    def __init__(
        self,
        log_path: Path | None = None,
        bus: Bus | None = None,
    ) -> None:
        self.log_path = Path(log_path) if log_path is not None else _DEFAULT_LOG
        self.bus = bus

    async def post_pair(self, intent: Intent) -> tuple[PaperOrder, PaperOrder]:
        yes = PaperOrder(
            order_id=str(uuid.uuid4()),
            token_id=intent.gap.yes_token_id,
            outcome="YES",
            side="BUY",
            path=intent.path,
            size=intent.size,
            limit=intent.yes_limit,
        )
        no = PaperOrder(
            order_id=str(uuid.uuid4()),
            token_id=intent.gap.no_token_id,
            outcome="NO",
            side="BUY",
            path=intent.path,
            size=intent.size,
            limit=intent.no_limit,
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "path": intent.path,
            "size": str(intent.size),
            "yes_limit": str(intent.yes_limit),
            "no_limit": str(intent.no_limit),
            "expected_net_edge": str(intent.expected_net_edge),
            "yes_order": yes.model_dump(mode="json"),
            "no_order": no.model_dump(mode="json"),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        if self.bus is not None:
            await self.bus.publish(Topic.INTENT, intent)
            await self.bus.publish(Topic.PAPER_FILL, PaperFill(yes=yes, no=no))
        return yes, no


class LiveBroker:
    """Raises RuntimeError unless live_allowed()."""

    def __init__(self, client: object, project_root: Path) -> None:
        if not live_allowed(project_root):
            raise RuntimeError(
                "live trading is not allowed: need ARB_MODE=live and a human ALLOW_LIVE dated today"
            )
        self.client = client
        self.project_root = Path(project_root)

    async def post_pair(self, intent: Intent) -> None:
        if not live_allowed(self.project_root):
            raise RuntimeError(
                "live trading is not allowed: need ARB_MODE=live and a human ALLOW_LIVE dated today"
            )
        raise RuntimeError("live SDK calls are not implemented")
