"""Record and load public book JSONL. Never places orders."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arb.books import Book, BookStore, Level


def event_ts_ms(event: dict[str, Any]) -> int:
    if "ts_ms" in event:
        return int(event["ts_ms"])
    raw = event.get("timestamp", 0)
    return int(raw) if raw is not None else 0


def snapshot_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Normalize a recorded book line into BookStore.apply_snapshot input."""
    token_id = event.get("token_id") or event.get("asset_id")
    return {
        "token_id": token_id,
        "asset_id": token_id,
        "bids": event.get("bids") or [],
        "asks": event.get("asks") or [],
        "tick": event.get("tick", event.get("tick_size", "0.01")),
        "min_order_size": event.get("min_order_size", event.get("minOrderSize", "5")),
        "ts_ms": event_ts_ms(event),
        "hash": event.get("hash"),
    }


def market_side_of(event: dict[str, Any]) -> str:
    side = event.get("market_side") or event.get("side") or ""
    return str(side).upper()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        rows.append(json.loads(text))
    return rows


def write_jsonl(path: Path, events: Iterable[dict[str, Any]]) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")


@dataclass(frozen=True)
class BookFrame:
    ts_ms: int
    yes: Book
    no: Book


def frames_from_events(events: Iterable[dict[str, Any]]) -> list[BookFrame]:
    """Replay recorded books in time order. Each frame is a post-event YES/NO pair."""
    ordered = sorted(events, key=event_ts_ms)
    store = BookStore()
    yes: Book | None = None
    no: Book | None = None
    frames: list[BookFrame] = []
    for event in ordered:
        if str(event.get("event_type", "book")).lower() not in {"book", "snapshot"}:
            continue
        book = store.apply_snapshot(snapshot_payload(event)).model_copy(deep=True)
        side = market_side_of(event)
        if side == "YES":
            yes = book
        elif side == "NO":
            no = book
        else:
            continue
        if yes is not None and no is not None:
            frames.append(
                BookFrame(
                    ts_ms=event_ts_ms(event),
                    yes=yes.model_copy(deep=True),
                    no=no.model_copy(deep=True),
                )
            )
    return frames


def _levels_to_rows(levels: list[Level]) -> list[dict[str, str]]:
    return [{"price": str(level.price), "size": str(level.size)} for level in levels]


def book_to_event(book: Book, market_side: str, condition_id: str) -> dict[str, Any]:
    """Public-book JSONL row compatible with frames_from_events. No orders."""
    return {
        "event_type": "book",
        "ts_ms": book.ts_ms,
        "timestamp": str(book.ts_ms),
        "condition_id": condition_id,
        "token_id": book.token_id,
        "asset_id": book.token_id,
        "market_side": str(market_side).upper(),
        "tick_size": str(book.tick),
        "min_order_size": str(book.min_order_size),
        "bids": _levels_to_rows(book.bids),
        "asks": _levels_to_rows(book.asks),
    }


class BookRecorder:
    """Append-only JSONL writer for public book events."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")

    def write(self, event: dict[str, Any]) -> None:
        self._handle.write(json.dumps(event, separators=(",", ":")) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()
