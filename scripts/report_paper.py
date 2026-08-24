#!/usr/bin/env python3
"""Summarize a paper run from gitignored JSONL logs.

Usage:
  uv run python scripts/report_paper.py
  uv run python scripts/report_paper.py --data-dir data/paper
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from decimal import Decimal
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def _halt_reason(data_dir: Path) -> str | None:
    db = data_dir / "state.sqlite"
    if not db.is_file():
        return None
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", ("halt_reason",)
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if row is None or not row[0]:
        return None
    return str(row[0])


def summarize_paper(data_dir: Path) -> dict:
    gaps = _read_jsonl(data_dir / "gaps.jsonl")
    intents = _read_jsonl(data_dir / "intents.jsonl")
    rejects = _read_jsonl(data_dir / "rejects.jsonl")

    maker_ev = Decimal("0")
    taker_ev = Decimal("0")
    for gap in gaps:
        if gap.get("maker_ev") is not None:
            maker_ev += Decimal(str(gap["maker_ev"]))
        if gap.get("taker_ev") is not None:
            taker_ev += Decimal(str(gap["taker_ev"]))

    reasons = Counter(str(row.get("reason", "unknown")) for row in rejects)
    for gap in gaps:
        reason = gap.get("reject_reason")
        if reason:
            reasons[str(reason)] += 0  # already counted in rejects.jsonl when present

    return {
        "gaps_seen": len(gaps),
        "intents_approved": len(intents),
        "estimated_maker_ev": maker_ev,
        "estimated_taker_ev": taker_ev,
        "reject_reasons": dict(reasons),
        "halt_reason": _halt_reason(data_dir),
    }


def format_report(stats: dict) -> str:
    lines = [
        "paper report",
        f"  gaps seen: {stats['gaps_seen']}",
        f"  intents approved: {stats['intents_approved']}",
        f"  estimated maker EV: {stats['estimated_maker_ev']}",
        f"  estimated taker EV: {stats['estimated_taker_ev']}",
        "  reject reasons:",
    ]
    halt_reason = stats.get("halt_reason")
    if halt_reason:
        lines.insert(1, f"  halt reason: {halt_reason}")
    reasons = stats["reject_reasons"]
    if not reasons:
        lines.append("    (none)")
    else:
        for reason, count in sorted(reasons.items()):
            lines.append(f"    {reason}: {count}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print paper-run stats from JSONL logs.")
    parser.add_argument("--data-dir", default="data/paper")
    args = parser.parse_args(argv)
    stats = summarize_paper(Path(args.data_dir))
    print(format_report(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
