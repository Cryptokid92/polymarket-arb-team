#!/usr/bin/env python3
"""Live-data paper runner. Uses AsyncPublicClient only. Never places orders.

Usage:
  uv run python scripts/paper_run.py --seconds 3600
  uv run python scripts/paper_run.py --all-markets --seconds 3600
  uv run python scripts/paper_run.py --once --data-dir /tmp/paper
  uv run python scripts/paper_run.py --all-markets --book-batch-size 50 --watch-pairs 40 --watch-rotate-s 1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

from polymarket import AsyncPublicClient
from polymarket.streams import MarketSpec

from arb.app import (
    BOOK_BATCH_SIZE,
    LIST_PAGE_SIZE,
    LIST_SAFETY_CAP,
    LIST_WINDOW_S,
    WATCH_PAIRS,
    WATCH_ROTATE_S,
    run_paper,
)
from arb.config import load_settings
from arb.preflight import run_preflight


class OfficialPublicAdapter:
    """Thin wrapper so the run loop never sees a trading client."""

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
        description="Paper runner: public books only. Refuses to place orders."
    )
    parser.add_argument("--seconds", type=int, default=3600, help="Run duration (default 3600)")
    parser.add_argument(
        "--max-markets",
        type=int,
        default=20,
        help=(
            "Max listed markets to scan (default 20). "
            "0 = no user cap; still windows at the documented safety ceiling "
            f"({LIST_SAFETY_CAP})."
        ),
    )
    parser.add_argument(
        "--all-markets",
        action="store_true",
        help=(
            "List open markets in official-cursor windows (same as --max-markets 0). "
            f"Window size {LIST_SAFETY_CAP}. Universe filter still applies. "
            f"REST books are batched ({BOOK_BATCH_SIZE} token ids). "
            f"Watch first {WATCH_PAIRS} pairs; rotate every {WATCH_ROTATE_S}s. "
            f"Swap listed windows every {LIST_WINDOW_S}s."
        ),
    )
    parser.add_argument(
        "--book-batch-size",
        type=int,
        default=BOOK_BATCH_SIZE,
        help=(
            f"Token ids per get_order_books call (default {BOOK_BATCH_SIZE}). "
            "Official CLOB rejects fat payloads; do not send the whole universe."
        ),
    )
    parser.add_argument(
        "--watch-pairs",
        type=int,
        default=WATCH_PAIRS,
        help=(
            f"YES/NO pairs to subscribe/poll at once (default {WATCH_PAIRS} = "
            f"{WATCH_PAIRS * 2} tokens). Remaining universe pairs rotate in."
        ),
    )
    parser.add_argument(
        "--watch-rotate-s",
        type=float,
        default=WATCH_ROTATE_S,
        help=(
            f"Seconds between watch-slice rotations (default {WATCH_ROTATE_S}). "
            "0 disables rotation."
        ),
    )
    parser.add_argument(
        "--list-window-s",
        type=float,
        default=LIST_WINDOW_S,
        help=(
            f"Seconds to stay on one 5000-market window before swapping "
            f"(default {LIST_WINDOW_S}). 0 swaps as soon as the next window "
            "is listed. Does not raise LIST_SAFETY_CAP."
        ),
    )
    parser.add_argument(
        "--paper-bankroll",
        default=None,
        help="Paper bankroll in pUSD (default 500 via PAPER_BANKROLL). Not real money.",
    )
    parser.add_argument("--data-dir", default="data/paper")
    parser.add_argument("--once", action="store_true", help="One list+book cycle, then exit")
    parser.add_argument(
        "--record-books",
        action="store_true",
        help="Dump watch-slice public books to data-dir/books.jsonl for backtest.",
    )
    parser.add_argument(
        "--place-orders",
        action="store_true",
        help="Rejected. This runner never places orders.",
    )
    return parser.parse_args(argv)


def resolve_max_markets(args: argparse.Namespace) -> int:
    """`--all-markets` or `--max-markets 0` means no user cap (safety ceiling still applies)."""
    if args.all_markets:
        return 0
    return int(args.max_markets)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.place_orders:
        print("paper_run: refuses to place orders", file=sys.stderr)
        return 2

    settings = load_settings()
    if args.paper_bankroll is not None:
        settings = settings.model_copy(
            update={"paper_bankroll": Decimal(str(args.paper_bankroll))}
        )
    project_root = Path.cwd()
    pre = run_preflight(settings, project_root)
    if not pre.ok:
        print(f"paper_run: preflight failed: {pre.reason}", file=sys.stderr)
        return 2
    if settings.arb_mode != "paper":
        print("paper_run: paper-only. Set ARB_MODE=paper.", file=sys.stderr)
        return 2

    return asyncio.run(_run(args, settings, project_root))


async def _run(args: argparse.Namespace, settings, project_root: Path) -> int:
    client = OfficialPublicAdapter(AsyncPublicClient())
    try:
        stats = await run_paper(
            client=client,
            settings=settings,
            project_root=project_root,
            data_dir=Path(args.data_dir),
            seconds=args.seconds,
            max_markets=resolve_max_markets(args),
            once=args.once,
            book_batch_size=args.book_batch_size,
            watch_pairs=args.watch_pairs,
            watch_rotate_s=args.watch_rotate_s,
            list_window_s=args.list_window_s,
            record_books=bool(args.record_books),
        )
    except Exception as exc:
        print(f"paper_run: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.close()
    print(
        "paper_run done:"
        f" listed={stats.markets_listed}"
        f" universe={stats.universe}"
        f" gaps={stats.gaps}"
        f" intents={stats.intents}"
        f" rejects={stats.rejects}"
        f" bankroll={stats.bankroll}"
        f" daily_pnl={stats.daily_pnl}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
