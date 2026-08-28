"""Reconstruct YES/NO books and walk ask depth. Buy the ask; size by depth."""

from __future__ import annotations

import hashlib
from decimal import ROUND_DOWN, Decimal
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from arb.money import d


def _reject_float(value: object, name: str) -> Decimal:
    if type(value) is float:
        raise TypeError(f"{name} must be Decimal, not float")
    if type(value) is Decimal:
        return value
    if type(value) is str or type(value) is int:
        return d(value)
    raise TypeError(f"{name} must be Decimal, not {type(value).__name__}")


class Level(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    price: Decimal
    size: Decimal

    @field_validator("price", "size", mode="before")
    @classmethod
    def _decimal_only(cls, value: object) -> Decimal:
        return _reject_float(value, "level")


class Book(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    token_id: str
    bids: list[Level]  # best first
    asks: list[Level]  # best first
    tick: Decimal
    min_order_size: Decimal
    ts_ms: int

    @field_validator("tick", "min_order_size", mode="before")
    @classmethod
    def _decimal_fields(cls, value: object) -> Decimal:
        return _reject_float(value, "book")


def _best_first_asks(levels: list[Level]) -> list[Level]:
    return sorted(levels, key=lambda lvl: lvl.price)


def _best_first_bids(levels: list[Level]) -> list[Level]:
    return sorted(levels, key=lambda lvl: lvl.price, reverse=True)


def walk_asks(asks: list[Level], shares: Decimal) -> tuple[Decimal, Decimal] | None:
    """Return (vwap, filled_shares) to buy `shares`. None if depth insufficient."""
    shares = _reject_float(shares, "shares")
    if shares <= 0:
        return None
    remaining = shares
    notional = Decimal("0")
    for level in _best_first_asks(asks):
        if level.size <= 0:
            continue
        take = remaining if remaining <= level.size else level.size
        notional += take * level.price
        remaining -= take
        if remaining == 0:
            return (notional / shares, shares)
    return None


def fillable_pair_size(
    yes_asks: list[Level],
    no_asks: list[Level],
    min_size: Decimal,
    max_shares: Decimal,
) -> Decimal:
    """Largest size where both walks succeed, stepped down to min_size grid."""
    min_size = _reject_float(min_size, "min_size")
    max_shares = _reject_float(max_shares, "max_shares")
    if min_size <= 0 or max_shares <= 0:
        return Decimal("0")
    yes_depth = sum((lvl.size for lvl in yes_asks), Decimal("0"))
    no_depth = sum((lvl.size for lvl in no_asks), Decimal("0"))
    cap = yes_depth
    if no_depth < cap:
        cap = no_depth
    if max_shares < cap:
        cap = max_shares
    size = (cap / min_size).to_integral_value(rounding=ROUND_DOWN) * min_size
    while size >= min_size:
        if walk_asks(yes_asks, size) is not None and walk_asks(no_asks, size) is not None:
            return size
        size -= min_size
    return Decimal("0")


def _levels_from_payload(rows: list[dict[str, Any]] | None) -> list[Level]:
    if not rows:
        return []
    return [Level(price=row["price"], size=row["size"]) for row in rows]


def _parse_ts_ms(payload: dict[str, Any]) -> int:
    raw = payload.get("ts_ms", payload.get("timestamp", 0))
    if raw is None:
        return 0
    return int(raw)


def _token_id_of(payload: dict[str, Any]) -> str:
    token_id = payload.get("token_id") or payload.get("asset_id")
    if not token_id:
        raise ValueError("snapshot/delta missing token_id")
    return str(token_id)


def _missing_decimal(value: object) -> bool:
    return value is None or value == ""


def book_from_payload(payload: dict[str, Any], *, previous: Book | None = None) -> Book:
    tick = payload.get("tick", payload.get("tick_size"))
    min_order = payload.get("min_order_size", payload.get("minOrderSize"))
    if _missing_decimal(tick):
        tick = previous.tick if previous is not None else Decimal("0.01")
    if _missing_decimal(min_order):
        min_order = previous.min_order_size if previous is not None else Decimal("5")
    return Book(
        token_id=_token_id_of(payload),
        bids=_best_first_bids(_levels_from_payload(payload.get("bids"))),
        asks=_best_first_asks(_levels_from_payload(payload.get("asks"))),
        tick=tick,
        min_order_size=min_order,
        ts_ms=_parse_ts_ms(payload),
    )


def _state_hash(book: Book) -> str:
    parts = [book.token_id]
    for side, levels in (("B", book.bids), ("A", book.asks)):
        for level in levels:
            parts.append(f"{side}:{level.price}:{level.size}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _apply_level_delta(levels: list[Level], price: Decimal, size: Decimal) -> list[Level]:
    kept = [lvl for lvl in levels if lvl.price != price]
    if size > 0:
        kept.append(Level(price=price, size=size))
    return kept


class BookStore:
    """In-memory YES/NO books reconstructed from snapshots and price_change deltas."""

    def __init__(self) -> None:
        self._books: dict[str, Book] = {}
        self._hashes: dict[str, str] = {}

    def get(self, token_id: str) -> Book | None:
        return self._books.get(token_id)

    def retain(self, token_ids: Sequence[str]) -> None:
        """Drop books that left the current list window. Keeps memory bounded."""
        keep = {str(token) for token in token_ids}
        self._books = {key: book for key, book in self._books.items() if key in keep}
        self._hashes = {key: digest for key, digest in self._hashes.items() if key in keep}

    def book_hash(self, token_id: str) -> str | None:
        return self._hashes.get(token_id)

    def apply_snapshot(self, payload: dict[str, Any]) -> Book:
        book = book_from_payload(payload, previous=self._books.get(_token_id_of(payload)))
        self._books[book.token_id] = book
        raw_hash = payload.get("hash")
        self._hashes[book.token_id] = str(raw_hash) if raw_hash else _state_hash(book)
        return book

    def apply_price_change(self, payload: dict[str, Any]) -> list[Book]:
        ts_ms = _parse_ts_ms(payload)
        changes = payload.get("price_changes") or payload.get("priceChanges") or []
        updated: list[Book] = []
        for change in changes:
            token_id = _token_id_of(change)
            current = self._books.get(token_id)
            if current is None:
                continue
            price = _reject_float(change["price"], "price")
            size = _reject_float(change["size"], "size")
            side = str(change.get("side", "")).upper()
            bids = list(current.bids)
            asks = list(current.asks)
            if side in {"BUY", "BID"}:
                bids = _best_first_bids(_apply_level_delta(bids, price, size))
            elif side in {"SELL", "ASK"}:
                asks = _best_first_asks(_apply_level_delta(asks, price, size))
            else:
                continue
            book = current.model_copy(update={"bids": bids, "asks": asks, "ts_ms": ts_ms})
            self._books[token_id] = book
            raw_hash = change.get("hash") or payload.get("hash")
            self._hashes[token_id] = str(raw_hash) if raw_hash else _state_hash(book)
            updated.append(book)
        return updated
