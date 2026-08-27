#!/usr/bin/env python3
"""Replay recorded public books through the Task 10 backtest. Paper only.

Usage:
  uv run python scripts/backtest_tape.py --tape data/paper/books.jsonl
  uv run python scripts/backtest_tape.py --tape tests/fixtures/recorded/gap_persist.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from arb.backtest import summarize_tape
from arb.recorder import load_jsonl


def format_tape_report(summary: dict) -> str:
    lines = [
        "paper tape backtest",
        f"  events: {summary['events']}",
        f"  trades: {summary['trades']}",
        f"  completed pairs: {summary['completed_pairs']}",
        f"  naked incidents: {summary['naked_incidents']}",
        f"  net pnl: {summary['net_pnl']}",
        f"  capital turns: {summary['capital_turns']}",
        f"  verdict: {summary['verdict']}",
    ]
    if summary["verdict"] == "non_positive":
        lines.append("  stop: net EV is not positive. Do not loosen risk. Do not go live.")
    if summary["verdict"] == "no_tape":
        lines.append("  no recorded books. Run paper_run --record-books or record_books.py.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backtest a recorded paper tape. Never places orders."
    )
    parser.add_argument("--tape", default="data/paper/books.jsonl")
    parser.add_argument(
        "--place-orders",
        action="store_true",
        help="Rejected. This backtest never places orders.",
    )
    args = parser.parse_args(argv)
    if args.place_orders:
        print("backtest_tape: refuses to place orders", file=sys.stderr)
        return 2
    path = Path(args.tape)
    if not path.is_file():
        summary = summarize_tape([])
        print(format_tape_report(summary))
        return 0
    events = load_jsonl(path)
    summary = summarize_tape(events)
    print(format_tape_report(summary))
    print(json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
