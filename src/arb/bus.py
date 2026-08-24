"""In-process async pubsub. No network."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from arb.messages import GapFound, Intent


class Topic:
    GAP_FOUND = "gap_found"
    INTENT = "intent"
    PAPER_FILL = "paper_fill"


class Bus:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[Any]]] = defaultdict(list)

    def subscribe(self, topic: str) -> asyncio.Queue[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._subs[topic].append(queue)
        return queue

    async def publish(self, topic: str, message: GapFound | Intent | object) -> None:
        for queue in self._subs.get(topic, []):
            await queue.put(message)
