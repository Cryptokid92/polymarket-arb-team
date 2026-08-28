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

from arb.backtest import replay_tape_path, summarize_tape


def format_edge_report(analysis: dict) -> str:
    histogram = analysis.get("edge_histogram") or {}
    thresholds = analysis.get("edge_thresholds") or {}
    lines = [
        "paper tape edges (miss vs absence)",
        f"  frames: {analysis.get('frames', 0)}",
        f"  ask-gap frames (VWAP sum <= 0.99): {analysis.get('ask_gap_frames', 0)}",
        f"  maker-quote frames: {analysis.get('maker_quote_frames', 0)}",
        f"  best ask edge: {analysis.get('best_ask_edge')}",
        f"  decision: {analysis.get('decision')}",
        "  thresholds:",
    ]
    if not thresholds:
        lines.append("    (none)")
    else:
        for key in ("gt_-0.005", "gt_-0.002", "gt_0", "gte_0.01"):
            lines.append(f"    {key}: {thresholds.get(key, 0)}")
    lines.append("  edge histogram:")
    if not histogram:
        lines.append("    (none)")
    else:
        for bucket, count in sorted(histogram.items()):
            lines.append(f"    {bucket}: {count}")
    if analysis.get("decision") == "capture":
        lines.append("  phase: B — tape has taker ask gaps. Capture; do not loosen min_edge.")
    else:
        lines.append(
            "  phase: C — asks stay complete. Maker completeness at min_edge 0.01."
        )
    return "\n".join(lines)


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
    if summary["verdict"] == "positive":
        lines.append("  honest tape EV is positive. Task 12 stays dark. No ALLOW_LIVE.")
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
        return 1
    analysis, summary = replay_tape_path(path)
    print(format_edge_report(analysis))
    print(format_tape_report(summary))
    print(json.dumps({"edges": analysis, "tape": summary}, separators=(",", ":")))
    if summary["verdict"] == "positive":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
