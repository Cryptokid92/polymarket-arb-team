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


def _stats_file(data_dir: Path) -> dict:
    path = data_dir / "stats.json"
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def summarize_paper(data_dir: Path) -> dict:
    gaps = _read_jsonl(data_dir / "gaps.jsonl")
    intents = _read_jsonl(data_dir / "intents.jsonl")
    rejects = _read_jsonl(data_dir / "rejects.jsonl")
    fills = _read_jsonl(data_dir / "fills.jsonl")
    snapshot = _stats_file(data_dir)

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

    completed = 0
    naked = 0
    for fill in fills:
        if fill.get("completed") is True:
            completed += 1
        if fill.get("naked") is True:
            naked += 1
    if snapshot.get("completed_pairs") is not None:
        completed = int(snapshot["completed_pairs"])
    if snapshot.get("naked_incidents") is not None:
        naked = int(snapshot["naked_incidents"])

    return {
        "gaps_seen": len(gaps),
        "intents_approved": len(intents),
        "estimated_maker_ev": maker_ev,
        "estimated_taker_ev": taker_ev,
        "reject_reasons": dict(reasons),
        "halt_reason": _halt_reason(data_dir),
        "best_edge": snapshot.get("best_edge"),
        "closest_condition_id": snapshot.get("closest_condition_id"),
        "closest_fillable": snapshot.get("closest_fillable"),
        "closest_in_watch": snapshot.get("closest_in_watch"),
        "closest_book_age_ms": snapshot.get("closest_book_age_ms"),
        "nearmiss_considers": snapshot.get("nearmiss_considers", 0),
        "edge_histogram": snapshot.get("edge_histogram") or {},
        "max_edge_window": snapshot.get("max_edge_window"),
        "edge_thresholds": snapshot.get("edge_thresholds") or {},
        "maker_quotes": snapshot.get("maker_quotes", 0),
        "completed_pairs": completed,
        "naked_incidents": naked,
    }


def format_report(stats: dict) -> str:
    lines = [
        "paper report",
        f"  gaps seen: {stats['gaps_seen']}",
        f"  maker quotes: {stats.get('maker_quotes', 0)}",
        f"  intents approved: {stats['intents_approved']}",
        f"  completed pairs: {stats.get('completed_pairs', 0)}",
        f"  naked incidents: {stats.get('naked_incidents', 0)}",
        f"  estimated maker EV: {stats['estimated_maker_ev']}",
        f"  estimated taker EV: {stats['estimated_taker_ev']}",
        f"  best edge this hour: {stats.get('best_edge')}",
        f"  max edge this window: {stats.get('max_edge_window')}",
        f"  closest pair: {stats.get('closest_condition_id')}",
        f"  closest fillable: {stats.get('closest_fillable')}",
        f"  closest in watch: {stats.get('closest_in_watch')}",
        f"  closest book age ms: {stats.get('closest_book_age_ms')}",
        f"  near-miss considers: {stats.get('nearmiss_considers', 0)}",
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
    histogram = stats.get("edge_histogram") or {}
    lines.append("  edge histogram:")
    if not histogram:
        lines.append("    (none)")
    else:
        for bucket, count in sorted(histogram.items()):
            lines.append(f"    {bucket}: {count}")
    thresholds = stats.get("edge_thresholds") or {}
    lines.append("  edge thresholds:")
    if not thresholds:
        lines.append("    (none)")
    else:
        for key in ("gt_-0.005", "gt_-0.002", "gt_0", "gte_0.01"):
            lines.append(f"    {key}: {thresholds.get(key, 0)}")
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
