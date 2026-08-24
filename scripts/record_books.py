#!/usr/bin/env python3
"""Record public YES/NO book JSONL. Never places orders.

Usage:
  python scripts/record_books.py --out data/books.jsonl --condition-id 0x...

Paper-only stub. A later task may stream from the official public client.
This script does not call the network, does not construct a secure trading
client, and refuses any order-placement flag.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record public book JSONL. Refuses to place orders."
    )
    parser.add_argument(
        "--out",
        default="data/books.jsonl",
        help="JSONL output path (gitignored under data/)",
    )
    parser.add_argument("--condition-id", default="", help="Market condition id")
    parser.add_argument(
        "--place-orders",
        action="store_true",
        help="Rejected. This recorder never places orders.",
    )
    args = parser.parse_args(argv)

    if args.place_orders:
        print("record_books: refuses to place orders", file=sys.stderr)
        return 2

    print("record_books: paper-only stub. Does not call the network.")
    print("Would record public books to", args.out)
    if args.condition_id:
        print("condition_id", args.condition_id)
    print("No secure trading client. No live orders. Public recording is later.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
