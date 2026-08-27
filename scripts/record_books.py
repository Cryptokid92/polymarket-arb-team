#!/usr/bin/env python3
"""Record public YES/NO book JSONL via AsyncPublicClient. Never places orders.

Usage:
  uv run python scripts/record_books.py --out data/paper/books.jsonl --seconds 60
  uv run python scripts/record_books.py --all-markets --once --out data/paper/books.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from polymarket import AsyncPublicClient
from polymarket.streams import MarketSpec

from arb.app import (
    BOOK_BATCH_SIZE,
    LIST_PAGE_SIZE,
    LIST_SAFETY_CAP,
    WATCH_PAIRS,
    WATCH_ROTATE_S,
    PublicApiError,
    _apply_update,
    _iter_listed_markets,
    _now_ms,
    fetch_book_batches,
    pair_token_ids,
    reject_universe,
    universe_pair,
    watch_slice,
)
from arb.books import BookStore
from arb.recorder import BookRecorder, book_to_event


class OfficialPublicAdapter:
    """Thin wrapper so the recorder never sees a trading client."""

    def __init__(self, client: AsyncPublicClient) -> None:
        self._client = client

    def list_markets(self, *, closed: bool = False, page_size: int = LIST_PAGE_SIZE, **kwargs):
        return self._client.list_markets(closed=closed, page_size=page_size, **kwargs)

    async def get_order_books(self, *, token_ids: list[str]):
        return await self._client.get_order_books(token_ids=token_ids)

    def subscribe(self, token_ids: list[str]):
        return self._client.subscribe(MarketSpec(token_ids=token_ids))

    async def close(self) -> None:
        await self._client.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record public books. Refuses to place orders."
    )
    parser.add_argument("--out", default="data/paper/books.jsonl")
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument(
        "--max-markets",
        type=int,
        default=20,
        help=f"Listed markets to scan (default 20). 0 = safety ceiling {LIST_SAFETY_CAP}.",
    )
    parser.add_argument(
        "--all-markets",
        action="store_true",
        help=f"List every open market (safety ceiling {LIST_SAFETY_CAP}).",
    )
    parser.add_argument("--book-batch-size", type=int, default=BOOK_BATCH_SIZE)
    parser.add_argument("--watch-pairs", type=int, default=WATCH_PAIRS)
    parser.add_argument("--watch-rotate-s", type=float, default=WATCH_ROTATE_S)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--condition-id", default="", help="Optional condition id filter")
    parser.add_argument(
        "--place-orders",
        action="store_true",
        help="Rejected. This recorder never places orders.",
    )
    return parser.parse_args(argv)


def resolve_max_markets(args: argparse.Namespace) -> int:
    if args.all_markets:
        return 0
    return int(args.max_markets)


async def record_public_books(
    client: object,
    *,
    out: Path,
    max_markets: int,
    once: bool,
    seconds: int,
    book_batch_size: int,
    watch_pairs: int,
    condition_id: str = "",
) -> int:
    """Write watch-slice public books. Returns lines written."""
    markets = await _iter_listed_markets(client, max_markets)
    pairs = []
    by_token: dict[str, object] = {}
    for market in markets:
        if reject_universe(market) is not None:
            continue
        pair = universe_pair(market)
        if condition_id and pair.condition_id != condition_id:
            continue
        pairs.append(pair)
        by_token[pair.yes_token_id] = pair
        by_token[pair.no_token_id] = pair
    if not pairs:
        raise PublicApiError("public API is unreachable: no v1 universe pairs to record")
    store = BookStore()
    recorder = BookRecorder(out)
    written = 0
    watch_n = max(1, int(watch_pairs))
    watched = watch_slice(pairs, 0, watch_n)
    watch_ids = {pair.condition_id for pair in watched}

    def dump_pair(pair: object) -> None:
        nonlocal written
        yes = store.get(pair.yes_token_id)
        no = store.get(pair.no_token_id)
        if yes is not None:
            recorder.write(book_to_event(yes, "YES", pair.condition_id))
            written += 1
        if no is not None:
            recorder.write(book_to_event(no, "NO", pair.condition_id))
            written += 1

    async def on_ok(books: object, _batch: list[str]) -> None:
        _apply_update(store, books, _now_ms())
        for pair in watched:
            dump_pair(pair)

    try:
        await fetch_book_batches(
            client,
            pair_token_ids(watched),
            batch_size=max(1, int(book_batch_size)),
            on_ok=on_ok,
            raise_if_all_fail=True,
        )
        if once:
            return written
        subscribe = getattr(client, "subscribe", None)
        if not callable(subscribe):
            return written
        stream = subscribe(pair_token_ids(watched))
        if hasattr(stream, "__await__"):
            stream = await stream
        deadline = asyncio.get_event_loop().time() + max(0, int(seconds))
        async for update in stream:
            _apply_update(store, update, _now_ms())
            tokens: list[str] = []
            if isinstance(update, (list, tuple)):
                tokens = [str(getattr(book, "token_id", "")) for book in update]
            else:
                payload = getattr(update, "payload", update)
                token = getattr(payload, "token_id", None)
                if token:
                    tokens.append(str(token))
            seen: set[str] = set()
            for token in tokens:
                pair = by_token.get(token)
                if pair is None or pair.condition_id in seen:
                    continue
                if pair.condition_id not in watch_ids:
                    continue
                seen.add(pair.condition_id)
                dump_pair(pair)
            if asyncio.get_event_loop().time() >= deadline:
                break
        return written
    finally:
        recorder.close()


async def _run(args: argparse.Namespace) -> int:
    client = OfficialPublicAdapter(AsyncPublicClient())
    try:
        written = await record_public_books(
            client,
            out=Path(args.out),
            max_markets=resolve_max_markets(args),
            once=bool(args.once),
            seconds=int(args.seconds),
            book_batch_size=int(args.book_batch_size),
            watch_pairs=int(args.watch_pairs),
            condition_id=str(args.condition_id or ""),
        )
    except PublicApiError as exc:
        print(f"record_books: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.close()
    print(f"record_books wrote {written} events to {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.place_orders:
        print("record_books: refuses to place orders", file=sys.stderr)
        return 2
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
