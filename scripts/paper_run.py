#!/usr/bin/env python3
"""Live-data paper runner. Uses AsyncPublicClient only. Never places orders.

Usage:
  uv run python scripts/paper_run.py --seconds 3600
  uv run python scripts/paper_run.py --once --data-dir /tmp/paper
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from polymarket import AsyncPublicClient
from polymarket.streams import MarketSpec

from arb.app import run_paper
from arb.config import load_settings
from arb.preflight import run_preflight


class OfficialPublicAdapter:
    """Thin wrapper so the run loop never sees a trading client."""

    def __init__(self, client: AsyncPublicClient) -> None:
        self._client = client

    def list_markets(self, *, closed: bool = False, page_size: int = 20, **kwargs):
        return self._client.list_markets(closed=closed, page_size=page_size, **kwargs)

    async def get_order_books(self, *, token_ids: list[str]):
        return await self._client.get_order_books(token_ids=token_ids)

    def subscribe(self, token_ids: list[str]):
        return self._client.subscribe(MarketSpec(token_ids=token_ids))

    async def close(self) -> None:
        await self._client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Paper runner: public books only. Refuses to place orders."
    )
    parser.add_argument("--seconds", type=int, default=3600, help="Run duration (default 3600)")
    parser.add_argument("--max-markets", type=int, default=20)
    parser.add_argument("--data-dir", default="data/paper")
    parser.add_argument("--once", action="store_true", help="One list+book cycle, then exit")
    parser.add_argument(
        "--place-orders",
        action="store_true",
        help="Rejected. This runner never places orders.",
    )
    args = parser.parse_args(argv)

    if args.place_orders:
        print("paper_run: refuses to place orders", file=sys.stderr)
        return 2

    settings = load_settings()
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
            max_markets=args.max_markets,
            once=args.once,
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
