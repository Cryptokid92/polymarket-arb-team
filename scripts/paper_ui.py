#!/usr/bin/env python3
"""Read-only local dashboard for paper runner JSONL. Never places orders.

Usage:
  uv run python scripts/paper_ui.py
  uv run python scripts/paper_ui.py --data-dir data/paper --port 8765
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
import time
from collections import Counter
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from arb.paper_control import (
    ROTATE_DEFAULT_S,
    ROTATE_MAX_S,
    ROTATE_MIN_S,
    apply_control,
    read_control,
    runner_is_alive,
)

BANNER = "PAPER MODE. Not live. Not financial advice."
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_DATA_DIR = "data/paper"
RECENT_LIMIT = 20
RUNNING_AGE_MS = 10_000
RECENT_AGE_MS = 60_000
LOG_NAMES = (
    "gaps.jsonl",
    "intents.jsonl",
    "rejects.jsonl",
    "fills.jsonl",
    "nearmiss.jsonl",
    "alerts.jsonl",
    "stats.json",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def read_stats_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _int_or_zero(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _file_mtime_ms(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        return path.stat().st_mtime_ns // 1_000_000
    except OSError:
        return None


def _row_ts_ms(row: dict[str, Any]) -> int | None:
    raw = row.get("ts_ms")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _sqlite_meta(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if row is None or row[0] in (None, ""):
        return None
    return str(row[0])


def _sqlite_halt_info(path: Path) -> tuple[bool | None, str | None]:
    if not path.is_file():
        return None, None
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None, None
    try:
        halted_row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", ("halted",)
        ).fetchone()
        reason_row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", ("halt_reason",)
        ).fetchone()
    except sqlite3.Error:
        return None, None
    finally:
        conn.close()
    if halted_row is None:
        halted = False
    else:
        halted = str(halted_row[0]) == "1"
    reason = str(reason_row[0]) if reason_row and reason_row[0] else None
    if reason == "":
        reason = None
    return halted, reason


def _halt_paths(data_dir: Path, project_root: Path) -> dict[str, Path]:
    return {
        "halt_file": project_root / "HALT",
        "halt_file_data": data_dir / "HALT",
        "sqlite_data_dir": data_dir / "state.sqlite",
        "sqlite_data": data_dir.parent / "state.sqlite",
        "sqlite_default": project_root / "data" / "state.sqlite",
    }


def read_halt(data_dir: Path, project_root: Path) -> dict[str, Any]:
    paths = _halt_paths(data_dir, project_root)
    halt_file = paths["halt_file"].is_file() or paths["halt_file_data"].is_file()
    sqlite_hits: list[tuple[str, Path, bool | None, str | None]] = []
    seen: set[Path] = set()
    for label, path in (
        ("sqlite_data_dir", paths["sqlite_data_dir"]),
        ("sqlite_data", paths["sqlite_data"]),
        ("sqlite_default", paths["sqlite_default"]),
    ):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not path.is_file():
            continue
        halted, reason = _sqlite_halt_info(path)
        sqlite_hits.append((label, path, halted, reason))

    sqlite_exists = bool(sqlite_hits)
    sqlite_halted = any(flag is True for _, _, flag, _reason in sqlite_hits)
    halt_reason: str | None = None
    for _label, _path, flag, reason in sqlite_hits:
        if flag is True and reason:
            halt_reason = reason
            break
    if halt_reason is None:
        for _label, _path, _flag, reason in sqlite_hits:
            if reason:
                halt_reason = reason
                break
    sources: list[str] = []
    if paths["halt_file"].is_file():
        sources.append("HALT")
    if paths["halt_file_data"].is_file():
        sources.append(str(paths["halt_file_data"]))
    for _label, path, flag, _reason in sqlite_hits:
        if flag is True:
            sources.append(f"{path}:halted")
        elif flag is False:
            sources.append(f"{path}:ok")
        else:
            sources.append(f"{path}:unreadable")
    return {
        "halted": halt_file or sqlite_halted,
        "halt_file": halt_file,
        "sqlite_exists": sqlite_exists,
        "sqlite_halted": sqlite_halted if sqlite_exists else None,
        "halt_reason": halt_reason,
        "sources": sources,
    }


def _latest_ms(*values: int | None) -> int | None:
    found = [value for value in values if value is not None]
    return max(found) if found else None


def _infer_run_status(last_event_age_ms: int | None) -> str:
    if last_event_age_ms is None:
        return "no_data"
    if last_event_age_ms <= RUNNING_AGE_MS:
        return "running"
    if last_event_age_ms <= RECENT_AGE_MS:
        return "recent"
    return "stale"


def _recent_gaps(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[-limit:]:
        out.append(
            {
                "ts_ms": row.get("ts_ms"),
                "condition_id": row.get("condition_id"),
                "raw_edge": row.get("raw_edge"),
                "yes_vwap": row.get("yes_vwap"),
                "no_vwap": row.get("no_vwap"),
                "fillable": row.get("fillable_shares", row.get("fillable")),
                "age": row.get("book_age_ms", row.get("age")),
                "reject_reason": row.get("reject_reason"),
            }
        )
    out.reverse()
    return out


def _recent_fills(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[-limit:]:
        out.append(
            {
                "ts_ms": row.get("ts_ms"),
                "path": row.get("path"),
                "size": row.get("size"),
                "yes_vwap": row.get("yes_vwap"),
                "no_vwap": row.get("no_vwap"),
                "pair_fees": row.get("pair_fees"),
                "cost": row.get("cost"),
                "pnl": row.get("pnl"),
                "bankroll": row.get("bankroll"),
            }
        )
    out.reverse()
    return out


def _recent_nearmiss(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[-limit:]:
        out.append(
            {
                "ts_ms": row.get("ts_ms"),
                "condition_id": row.get("condition_id"),
                "raw_edge": row.get("raw_edge"),
                "yes_vwap": row.get("yes_vwap"),
                "no_vwap": row.get("no_vwap"),
                "fillable": row.get("fillable_shares", row.get("fillable")),
                "age": row.get("book_age_ms", row.get("age")),
                "in_watch": row.get("in_watch"),
                "thin": row.get("thin"),
            }
        )
    out.reverse()
    return out


def _recent_alerts(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[-limit:]:
        out.append(
            {
                "ts_ms": row.get("ts_ms"),
                "condition_id": row.get("condition_id"),
                "path": row.get("path"),
                "size": row.get("size"),
                "raw_edge": row.get("raw_edge"),
                "expected_net_edge": row.get("expected_net_edge"),
                "yes_vwap": row.get("yes_vwap"),
                "no_vwap": row.get("no_vwap"),
                "outcome": row.get("outcome"),
            }
        )
    out.reverse()
    return out


def _recent_intents(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[-limit:]:
        out.append(
            {
                "path": row.get("path"),
                "size": row.get("size"),
                "expected_net_edge": row.get("expected_net_edge"),
                "yes_limit": row.get("yes_limit"),
                "no_limit": row.get("no_limit"),
            }
        )
    out.reverse()
    return out


def summarize_dashboard(
    data_dir: Path,
    *,
    project_root: Path | None = None,
    now_ms: int | None = None,
    recent_limit: int = RECENT_LIMIT,
) -> dict[str, Any]:
    """Read-only summary. Missing logs yield zeros. Does not invent trades."""
    root = Path(project_root) if project_root is not None else Path.cwd()
    clock = _now_ms() if now_ms is None else now_ms
    gaps = read_jsonl(data_dir / "gaps.jsonl")
    intents = read_jsonl(data_dir / "intents.jsonl")
    rejects = read_jsonl(data_dir / "rejects.jsonl")
    fills = read_jsonl(data_dir / "fills.jsonl")
    nearmiss = read_jsonl(data_dir / "nearmiss.jsonl")
    alerts = read_jsonl(data_dir / "alerts.jsonl")
    stats = read_stats_file(data_dir / "stats.json")
    control = read_control(data_dir)

    jsonl_gaps = len(gaps)
    jsonl_intents = len(intents)
    jsonl_rejects = len(rejects)
    jsonl_fills = len(fills)
    reasons = Counter(str(row.get("reason", "unknown")) for row in rejects)

    markets_listed = 0
    universe = 0
    bankroll = "500"
    daily_pnl = "0"
    completed_pairs = 0
    naked_incidents = 0
    watching = 0
    nearmiss_considers = 0
    watch_rows: list[dict[str, Any]] = []
    list_window = 1
    list_wraps = 0
    list_next_queued = False
    list_cursor = None
    best_edge = None
    closest: dict[str, Any] | None = None
    edge_histogram: dict[str, Any] = {}
    if stats is not None:
        markets_listed = _int_or_zero(stats.get("markets_listed"))
        universe = _int_or_zero(stats.get("universe"))
        watching = _int_or_zero(stats.get("watching"))
        nearmiss_considers = _int_or_zero(stats.get("nearmiss_considers"))
        list_window = max(1, _int_or_zero(stats.get("list_window")) or 1)
        list_wraps = _int_or_zero(stats.get("list_wraps"))
        list_next_queued = stats.get("list_next_queued") is True
        if stats.get("list_cursor") is not None:
            list_cursor = str(stats.get("list_cursor"))
        jsonl_gaps = max(jsonl_gaps, _int_or_zero(stats.get("gaps")))
        jsonl_intents = max(jsonl_intents, _int_or_zero(stats.get("intents")))
        jsonl_rejects = max(jsonl_rejects, _int_or_zero(stats.get("rejects")))
        jsonl_fills = max(jsonl_fills, _int_or_zero(stats.get("fills")))
        extra = stats.get("reject_reasons")
        if isinstance(extra, dict) and not reasons:
            for key, value in extra.items():
                reasons[str(key)] += _int_or_zero(value)
        if stats.get("bankroll") is not None:
            bankroll = str(stats.get("bankroll"))
        if stats.get("daily_pnl") is not None:
            daily_pnl = str(stats.get("daily_pnl"))
        completed_pairs = _int_or_zero(stats.get("completed_pairs"))
        naked_incidents = _int_or_zero(stats.get("naked_incidents"))
        if stats.get("best_edge") is not None:
            best_edge = str(stats.get("best_edge"))
        hist = stats.get("edge_histogram")
        if isinstance(hist, dict):
            edge_histogram = {str(key): _int_or_zero(value) for key, value in hist.items()}
        raw_watch = stats.get("watch")
        if isinstance(raw_watch, list):
            for row in raw_watch:
                if not isinstance(row, dict) or not row.get("condition_id"):
                    continue
                watch_rows.append(
                    {
                        "condition_id": str(row.get("condition_id")),
                        "label": str(row.get("label") or row.get("condition_id")),
                        "pinned": row.get("pinned") is True,
                        "raw_edge": (
                            None if row.get("raw_edge") is None else str(row.get("raw_edge"))
                        ),
                    }
                )
        if stats.get("closest_condition_id"):
            closest = {
                "condition_id": stats.get("closest_condition_id"),
                "raw_edge": stats.get("best_edge"),
                "fillable": stats.get("closest_fillable"),
                "book_age_ms": stats.get("closest_book_age_ms"),
                "in_watch": stats.get("closest_in_watch"),
                "thin": stats.get("closest_thin"),
            }

    sqlite_path = data_dir / "state.sqlite"
    sqlite_bankroll = _sqlite_meta(sqlite_path, "bankroll")
    sqlite_pnl = _sqlite_meta(sqlite_path, "daily_pnl")
    if stats is None or stats.get("bankroll") is None:
        if sqlite_bankroll is not None:
            bankroll = sqlite_bankroll
    if stats is None or stats.get("daily_pnl") is None:
        if sqlite_pnl is not None:
            daily_pnl = sqlite_pnl

    last_ts: int | None = None
    for rows in (gaps, intents, rejects, fills, nearmiss, alerts):
        for row in rows:
            ts = _row_ts_ms(row)
            if ts is not None and (last_ts is None or ts > last_ts):
                last_ts = ts

    last_mtime: int | None = None
    for name in LOG_NAMES:
        mtime = _file_mtime_ms(data_dir / name)
        if mtime is not None and (last_mtime is None or mtime > last_mtime):
            last_mtime = mtime

    heartbeat_ms = _row_ts_ms({"ts_ms": stats.get("heartbeat_ms")}) if stats else None

    last_activity_ms = _latest_ms(last_ts, heartbeat_ms, last_mtime)
    if last_activity_ms is not None:
        last_event_age_ms = max(0, clock - last_activity_ms)
    else:
        last_event_age_ms = None

    run_status = _infer_run_status(last_event_age_ms)
    if control.paused:
        run_status = "paused"

    rotate_s = (
        control.rotate_s if control.rotate_s is not None else ROTATE_DEFAULT_S
    )
    return {
        "banner": BANNER,
        "mode": "paper",
        "run_status": run_status,
        "last_event_age_ms": last_event_age_ms,
        "last_log_mtime_ms": last_mtime,
        "heartbeat_ms": heartbeat_ms,
        "counts": {
            "markets_listed": markets_listed,
            "universe": universe,
            "gaps": jsonl_gaps,
            "intents": jsonl_intents,
            "rejects": jsonl_rejects,
            "fills": jsonl_fills,
        },
        "paper": {
            "bankroll": bankroll,
            "daily_pnl": daily_pnl,
            "completed_pairs": completed_pairs,
            "naked_incidents": naked_incidents,
            "watching": watching,
            "nearmiss_considers": nearmiss_considers,
            "list_window": list_window,
            "list_wraps": list_wraps,
            "list_next_queued": list_next_queued,
            "list_cursor": list_cursor,
            "best_edge": best_edge,
            "closest": closest,
            "edge_histogram": edge_histogram,
            "watch": watch_rows,
        },
        "closest": closest,
        "best_edge": best_edge,
        "recent_nearmiss": _recent_nearmiss(nearmiss, recent_limit),
        "recent_alerts": _recent_alerts(alerts, recent_limit),
        "control": {
            "paused": control.paused,
            "rotate_s": rotate_s,
            "rotate_min_s": ROTATE_MIN_S,
            "rotate_max_s": ROTATE_MAX_S,
            "runner_alive": runner_is_alive(data_dir),
        },
        "reject_reasons": dict(sorted(reasons.items())),
        "recent_gaps": _recent_gaps(gaps, recent_limit),
        "recent_intents": _recent_intents(intents, recent_limit),
        "recent_fills": _recent_fills(fills, recent_limit),
        "halt": read_halt(data_dir, root),
    }


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _esc(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _age_label(age_ms: int | None) -> str:
    if age_ms is None:
        return "no events"
    if age_ms < 1000:
        return f"{age_ms} ms ago"
    seconds = age_ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s ago"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m ago"
    hours = minutes / 60
    return f"{hours:.1f}h ago"


_HIST_ORDER: tuple[tuple[str, str, str], ...] = (
    ("lt_-0.05", "< −5¢", "cold"),
    ("-0.05_-0.02", "−5 to −2¢", "cold"),
    ("-0.02_-0.01", "−2 to −1¢", "cool"),
    ("-0.01_0", "−1 to 0¢", "close"),
    ("0_0.005", "0 to +0.5¢", "near"),
    ("0.005_0.01", "+0.5 to +1¢", "near"),
    ("0.01_0.02", "+1 to +2¢", "hot"),
    ("gte_0.02", "≥ +2¢", "hot"),
    ("none", "thin", "thin"),
)


def _rows_html(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return '<p class="empty">None yet. The runner has not written this log.</p>'
    head = "".join(f"<th>{_esc(title)}</th>" for title, _key in columns)
    body_parts: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(key))}</td>" for _title, key in columns)
        body_parts.append(f"<tr>{cells}</tr>")
    return (
        f'<table class="sheet"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body_parts)}</tbody></table>"
    )


def _parse_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _edge_tone(raw: object) -> str:
    edge = _parse_decimal(raw)
    if edge is None:
        return "muted"
    if edge >= Decimal("0.01"):
        return "hot"
    if edge >= Decimal("0"):
        return "near"
    if edge >= Decimal("-0.01"):
        return "close"
    return "cold"


def _edge_meter_html(raw: object) -> str:
    """Visual walk from cold books toward hunt. Does not change min_edge."""
    lo = Decimal("-0.05")
    hi = Decimal("0.02")
    hunt = Decimal("0.01")
    span = hi - lo
    edge = _parse_decimal(raw)
    if edge is None:
        return '<div class="meter empty-meter">No walked edge yet</div>'
    clamped = min(hi, max(lo, edge))
    pct = int((clamped - lo) * Decimal(100) / span)
    hunt_pct = int((hunt - lo) * Decimal(100) / span)
    need = hunt - edge
    need_q = need.quantize(Decimal("0.0001"))
    need_label = f"need {need_q:+} to hunt" if need > 0 else "at or above min_edge"
    return (
        f'<div class="meter" aria-label="edge meter">'
        f'<div class="meter-track">'
        f'<div class="meter-hunt" style="left:{hunt_pct}%"></div>'
        f'<div class="meter-dot { _edge_tone(edge) }" style="left:{pct}%"></div>'
        f"</div>"
        f'<div class="meter-scale"><span>−5¢</span><span>hunt +1¢</span><span>+2¢</span></div>'
        f'<p class="meter-need">{_esc(need_label)}</p>'
        f"</div>"
    )


def _bar_track(count: int, peak: int, tone: str, label: str, raw_key: str) -> str:
    width = 0
    if peak > 0 and count > 0:
        width = min(100, max(2, int(Decimal(count) * Decimal(100) / Decimal(peak))))
    return (
        f'<div class="bar" data-bucket="{_esc(raw_key)}">'
        f'<div class="bar-meta"><span class="bar-label">{_esc(label)}</span>'
        f'<span class="bar-key">{_esc(raw_key)}</span>'
        f'<span class="bar-n">{_esc(count)}</span></div>'
        f'<div class="bar-track"><div class="bar-fill {tone}" style="width:{width}%"></div></div>'
        f"</div>"
    )


def _hist_bars_html(histogram: dict[str, Any]) -> str:
    counts = {str(key): _int_or_zero(value) for key, value in histogram.items()}
    ordered_keys = [key for key, _label, _tone in _HIST_ORDER]
    extras = [key for key in counts if key not in ordered_keys]
    peak = max([counts.get(key, 0) for key in (*ordered_keys, *extras)], default=0)
    if peak <= 0 and not counts:
        return '<p class="empty">No walked books yet. Near-misses are not gaps.</p>'
    parts: list[str] = []
    for key, label, tone in _HIST_ORDER:
        parts.append(_bar_track(counts.get(key, 0), peak, tone, label, key))
    for key in extras:
        parts.append(_bar_track(counts[key], peak, "thin", key, key))
    return f'<div class="bars">{"".join(parts)}</div>'


def _reason_bars_html(reasons: dict[str, Any]) -> str:
    if not reasons:
        return (
            '<table class="sheet"><thead><tr><th>reason</th><th>count</th></tr></thead>'
            '<tbody><tr><td colspan="2" class="empty">None</td></tr></tbody></table>'
        )
    peak = max((_int_or_zero(count) for count in reasons.values()), default=0)
    rows = "".join(
        f"<tr><td>{_esc(reason)}</td><td>{_esc(count)}</td></tr>"
        for reason, count in reasons.items()
    )
    bars = "".join(
        _bar_track(_int_or_zero(count), peak, "cool", str(reason), str(reason))
        for reason, count in reasons.items()
    )
    return (
        f'<div class="bars">{bars}</div>'
        f'<table class="sheet reason-table"><thead><tr><th>reason</th><th>count</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def _watch_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">No watch slice yet. The runner has not subscribed.</p>'
    parts: list[str] = []
    for row in rows:
        tone = _edge_tone(row.get("raw_edge"))
        kind = "pin" if row.get("pinned") else "rot"
        kind_label = "pin" if row.get("pinned") else "rot"
        edge = row.get("raw_edge")
        edge_txt = "—" if edge is None else str(edge)
        parts.append(
            f'<div class="watch-row {kind} {tone}">'
            f'<span class="watch-kind">{kind_label}</span>'
            f'<span class="watch-label" title="{_esc(row.get("condition_id"))}">'
            f'{_esc(row.get("label"))}</span>'
            f'<span class="watch-edge">{_esc(edge_txt)}</span>'
            f'<span class="watch-id">{_esc(row.get("condition_id"))}</span>'
            f"</div>"
        )
    return f'<div class="watch-list">{"".join(parts)}</div>'


def _metric(label: str, value: object, *, extra: str = "", tone: str = "") -> str:
    klass = f"metric {tone}".strip()
    return (
        f'<div class="{klass}"><span class="k">{_esc(label)}</span>'
        f'<span class="v">{_esc(value)}</span>{extra}</div>'
    )


def render_html(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    paper = summary.get("paper") or {}
    control = summary.get("control") or {}
    halt = summary["halt"]
    reasons = summary["reject_reasons"]
    bankroll = paper.get("bankroll", "500")
    daily_pnl = str(paper.get("daily_pnl", "0"))
    completed_pairs = paper.get("completed_pairs", 0)
    naked_incidents = paper.get("naked_incidents", 0)
    closest = summary.get("closest") or paper.get("closest")
    best_edge = summary.get("best_edge") or paper.get("best_edge")
    histogram = paper.get("edge_histogram") or {}
    watching = paper.get("watching", 0)
    considers = paper.get("nearmiss_considers", 0)
    watch_rows = paper.get("watch") or []
    pnl_lost = daily_pnl.startswith("-")
    pnl_label = "lost" if pnl_lost else "earned"
    pnl_class = "lost" if pnl_lost else "earned"
    rotate_s = control.get("rotate_s", ROTATE_DEFAULT_S)
    paused = bool(control.get("paused"))
    runner_alive = "yes" if control.get("runner_alive") else "no"
    edge_tone = _edge_tone(best_edge)
    if closest:
        closest_html = (
            f'<div class="hero-edge {edge_tone}">'
            f'<div class="hero-k">best walked edge</div>'
            f'<div class="hero-n">{_esc(best_edge if best_edge is not None else "—")}</div>'
            f"{_edge_meter_html(best_edge)}"
            f'<div class="hero-chips">'
            f'<span>pair {_esc(closest.get("condition_id"))}</span>'
            f'<span>fillable {_esc(closest.get("fillable"))}</span>'
            f'<span>age {_esc(closest.get("book_age_ms"))} ms</span>'
            f'<span>watch {_esc(closest.get("in_watch"))}</span>'
            f'<span>thin {_esc(closest.get("thin"))}</span>'
            f"</div></div>"
        )
    else:
        closest_html = '<p class="empty">No walked books yet. Near-misses are not gaps.</p>'
    halt_class = "halted" if halt.get("halted") else "ok"
    halt_label = "HALTED" if halt.get("halted") else "not halted"
    sources = ", ".join(halt.get("sources") or ()) or "none"
    sqlite_bit = "yes" if halt.get("sqlite_exists") else "no"
    halt_file_bit = "yes" if halt.get("halt_file") else "no"
    halt_reason = halt.get("halt_reason") or "none"
    if halt.get("halted") and halt_reason == "ws_stale":
        halt_hint = (
            "ws_stale means the stream or REST probe failed, not daily loss. "
            "Start (human) clears it when no HALT file is present."
        )
    elif halt.get("halted") and halt_reason == "daily_loss":
        halt_hint = "daily_loss is a real kill. Human Start required. Not auto-resumed."
    elif halt.get("halted"):
        halt_hint = f"Halt reason {halt_reason}. Not auto-resumed."
    else:
        halt_hint = ""
    list_window = paper.get("list_window", 1)
    list_next = paper.get("list_next_queued") is True
    list_note = (
        f"list window {_esc(list_window)}"
        + (" · next 5000 queued" if list_next else "")
    )
    run_status = str(summary["run_status"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Paper dashboard — completeness arb</title>
  <meta name="robots" content="noindex">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="2">
  <style>
    :root {{
      color-scheme: dark;
      --bg: #07090d;
      --panel: #10151d;
      --panel-2: #161d28;
      --line: #243044;
      --ink: #e7eef8;
      --muted: #8b9bb0;
      --amber: #f5c14a;
      --amber-dim: #3a2d0a;
      --cyan: #5eead4;
      --green: #34d399;
      --red: #fb7185;
      --cool: #60a5fa;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; margin: 0; }}
    body {{
      font-family: "Segoe UI", "IBM Plex Sans", system-ui, sans-serif;
      background:
        radial-gradient(1200px 600px at 10% -10%, #163047 0%, transparent 50%),
        radial-gradient(900px 500px at 100% 0%, #2a1d08 0%, transparent 42%),
        var(--bg);
      color: var(--ink);
      overflow: hidden;
    }}
    .board {{
      height: 100vh;
      height: 100dvh;
      display: grid;
      grid-template-rows: auto auto auto minmax(0, 1fr) auto;
      gap: 10px;
      padding: 10px 12px 8px;
    }}
    header {{
      background: linear-gradient(90deg, #5a4308, #3a2d0a);
      color: var(--amber);
      padding: 8px 14px;
      border: 1px solid #8a6a1a;
      border-radius: 10px;
      font-weight: 800;
      letter-spacing: 0.04em;
    }}
    .top {{
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.7fr);
      gap: 10px;
      min-height: 0;
    }}
    .status, .controls, .panel {{
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      backdrop-filter: blur(8px);
    }}
    .status {{
      display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px;
      font-size: 13px; color: var(--muted);
    }}
    .pill {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 3px 9px; border-radius: 999px; font-weight: 700;
      font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase;
    }}
    .pill.running, .pill.recent {{ background: #0f2d22; color: var(--green); }}
    .pill.paused, .pill.stale, .pill.no_data {{ background: #2a2412; color: var(--amber); }}
    .ok {{ color: var(--green); }}
    .earned {{ color: var(--green); }}
    .lost {{ color: var(--red); }}
    .halted {{ color: var(--red); font-weight: 700; }}
    .halt-hint {{ color: var(--amber); font-size: 12px; }}
    .controls {{
      display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px;
    }}
    .controls h2 {{ margin: 0 8px 0 0; }}
    .controls button {{
      background: #1c2736; color: var(--ink); border: 1px solid var(--line);
      border-radius: 8px; padding: 7px 12px; font-weight: 700; cursor: pointer;
    }}
    .controls button:hover {{ border-color: var(--cyan); color: var(--cyan); }}
    .controls input[type="range"] {{ width: 140px; vertical-align: middle; accent-color: var(--cyan); }}
    .controls .hint {{ color: var(--muted); font-size: 11px; line-height: 1.35; margin: 0; flex: 1 1 180px; }}
    h2 {{
      margin: 0 0 8px; font-size: 11px; letter-spacing: 0.08em;
      text-transform: uppercase; color: var(--cyan);
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(108px, 1fr));
      gap: 8px;
    }}
    .metric, .hero-edge, .panel {{
      background: color-mix(in srgb, var(--panel) 92%, transparent);
      border: 1px solid var(--line);
      border-radius: 12px;
    }}
    .metric {{ padding: 8px 10px; min-width: 0; }}
    .metric .k, .hero-k {{
      display: block; color: var(--muted); font-size: 10px;
      letter-spacing: 0.06em; text-transform: uppercase;
    }}
    .metric .v {{
      display: block; font-family: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
      font-size: clamp(18px, 2.1vw, 28px); font-weight: 700; line-height: 1.15;
      margin-top: 2px;
    }}
    .metric.wide {{ grid-column: span 1; }}
    .main {{
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
      grid-template-rows: minmax(0, 1fr) auto;
      gap: 10px;
      min-height: 0;
    }}
    .panel {{
      padding: 10px 12px; min-height: 0; overflow: auto;
      display: flex; flex-direction: column;
    }}
    .panel-watch {{ grid-column: 1; grid-row: 1 / span 2; overflow: hidden; }}
    .panel-hist {{ grid-column: 2; grid-row: 1; }}
    .panel-logs {{
      grid-column: 2; grid-row: 2; max-height: 28vh;
      display: grid; grid-template-columns: 1fr 1fr; gap: 8px 14px;
    }}
    .panel-logs h2 {{ margin-top: 6px; }}
    .panel-logs > div > h2:first-child {{ margin-top: 0; }}
    .panel .bars {{ flex: 1; justify-content: space-evenly; }}
    .hero-edge {{ padding: 2px 2px 0; flex: 0 0 auto; }}
    .watch-wrap {{ flex: 1; min-height: 0; display: flex; flex-direction: column; margin-top: 8px; }}
    .watch-list {{
      flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 3px;
    }}
    .watch-row {{
      display: grid; grid-template-columns: 36px minmax(0, 1fr) auto;
      gap: 8px; align-items: center;
      background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px;
      padding: 3px 8px; font-size: 12px;
    }}
    .watch-row.pin {{ border-color: #8a6a1a; box-shadow: inset 3px 0 0 var(--amber); }}
    .watch-kind {{
      text-transform: uppercase; letter-spacing: 0.06em; font-size: 10px; color: var(--amber);
      font-weight: 800;
    }}
    .watch-row.rot .watch-kind {{ color: var(--cyan); }}
    .watch-label {{
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink);
    }}
    .watch-edge {{
      font-family: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
      font-weight: 700;
    }}
    .watch-row.hot .watch-edge {{ color: var(--green); }}
    .watch-row.near .watch-edge, .watch-row.close .watch-edge {{ color: var(--amber); }}
    .watch-row.cold .watch-edge {{ color: var(--red); }}
    .watch-id {{ display: none; }}
    .hero-n {{
      font-family: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
      font-size: clamp(28px, 3.6vw, 48px); font-weight: 800; line-height: 1;
      margin: 2px 0 4px;
    }}
    .hero-edge.hot .hero-n {{ color: var(--green); }}
    .hero-edge.near .hero-n {{ color: var(--amber); }}
    .hero-edge.close .hero-n {{ color: #fbbf24; }}
    .hero-edge.cold .hero-n {{ color: var(--red); }}
    .hero-chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .hero-chips span {{
      background: var(--panel-2); border: 1px solid var(--line);
      border-radius: 999px; padding: 3px 8px; font-size: 11px; color: var(--muted);
    }}
    .bars {{ display: flex; flex-direction: column; gap: 6px; }}
    .bar-meta {{
      display: grid; grid-template-columns: 1fr auto auto; gap: 8px;
      font-size: 11px; color: var(--muted);
    }}
    .bar-n, .v, td {{ font-variant-numeric: tabular-nums; }}
    .bar-key {{ color: #6b7c93; font-family: ui-monospace, Menlo, Consolas, monospace; }}
    .bar-track {{
      height: 14px; background: #1a2230; border-radius: 99px; overflow: hidden;
      box-shadow: inset 0 0 0 1px #243044;
    }}
    .bar-fill {{ height: 100%; border-radius: 99px; }}
    .bar-fill.cold {{ background: linear-gradient(90deg, #9f1239, #fb7185); box-shadow: 0 0 12px #fb718866; }}
    .bar-fill.cool {{ background: linear-gradient(90deg, #1d4ed8, var(--cool)); }}
    .bar-fill.close {{ background: linear-gradient(90deg, #b45309, #fbbf24); box-shadow: 0 0 12px #fbbf2466; }}
    .bar-fill.near {{ background: linear-gradient(90deg, #a16207, var(--amber)); box-shadow: 0 0 14px #f5c14a66; }}
    .bar-fill.hot {{ background: linear-gradient(90deg, #047857, var(--green)); box-shadow: 0 0 14px #34d39966; }}
    .bar-fill.thin {{ background: #64748b; }}
    .meter {{ margin: 6px 0 8px; }}
    .meter-track {{
      position: relative; height: 16px; border-radius: 99px;
      background: linear-gradient(90deg, #fb7185 0%, #fbbf24 60%, #34d399 85%, #5eead4 100%);
      box-shadow: inset 0 0 0 1px #243044;
    }}
    .meter-hunt {{
      position: absolute; top: -3px; bottom: -3px; width: 2px;
      background: #fff; box-shadow: 0 0 8px #fff;
    }}
    .meter-dot {{
      position: absolute; top: 50%; width: 14px; height: 14px; margin: -7px 0 0 -7px;
      border-radius: 50%; background: #fff; border: 2px solid #0b0d12;
      box-shadow: 0 0 0 3px #f5c14a88;
    }}
    .meter-scale {{
      display: flex; justify-content: space-between; color: var(--muted);
      font-size: 10px; margin-top: 4px;
    }}
    .meter-need {{ margin: 6px 0 0; color: var(--amber); font-size: 13px; font-weight: 700; }}
    .reason-table {{ display: none; }}
    table.sheet {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{
      text-align: left; padding: 5px 6px; border-bottom: 1px solid var(--line);
      font-family: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 28vw;
    }}
    th {{ color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 10px; }}
    .empty {{ color: var(--muted); }}
    .reason-table {{ margin-top: 8px; }}
    footer {{ color: #6b7c93; font-size: 11px; padding: 0 4px; }}
    @media (max-width: 1100px) {{
      body {{ overflow: auto; }}
      .board {{ height: auto; min-height: 100vh; }}
      .top, .main {{ grid-template-columns: 1fr; grid-template-rows: auto; }}
      .panel-watch, .panel-hist, .panel-logs {{
        grid-column: auto; grid-row: auto; max-height: none;
      }}
      .panel-logs {{ display: flex; }}
      .metrics {{ grid-template-columns: repeat(auto-fit, minmax(108px, 1fr)); }}
    }}
  </style>
</head>
<body>
  <div class="board">
  <header>{_esc(summary["banner"])}</header>
  <div class="top">
    <div class="status">
      <span class="pill { _esc(run_status) }">{_esc(run_status)}</span>
      Run status: <strong>{_esc(run_status)}</strong>
      · last event {_esc(_age_label(summary.get("last_event_age_ms")))}
      · halt: <span class="{halt_class}">{halt_label}</span>
      · halt reason: {_esc(halt_reason)}
      {f'<span class="halt-hint">{_esc(halt_hint)}</span>' if halt_hint else ""}
      · HALT file: {halt_file_bit}
      · sqlite: {sqlite_bit}
      · sources: {_esc(sources)}
    </div>
    <div class="controls">
      <h2>Paper controls (127.0.0.1 only)</h2>
      <button type="button" id="btn-start">Start</button>
      <button type="button" id="btn-stop">Stop</button>
      <label>Watch rotate
        <input type="range" id="rotate" min="{ROTATE_MIN_S}" max="{ROTATE_MAX_S}"
               value="{_esc(rotate_s)}">
        <span id="rotate-val">{_esc(rotate_s)}s</span>
      </label>
      <p class="hint">Start/Stop pauses or launches paper_run (ARB_MODE=paper).
      Slider is watch-slice interval ({ROTATE_MIN_S}–{ROTATE_MAX_S}s). Does not
      change stale_ms, min_edge, max_gap, universe filters, or bankroll rules.
      Stop does not place or cancel live orders.</p>
    </div>
  </div>
  <div class="metrics">
      {_metric("paper bankroll", bankroll, extra='<span class="k">not real money</span>')}
      {_metric(f"realized PnL ({pnl_label})", daily_pnl, tone=pnl_class)}
      {_metric("markets listed", counts["markets_listed"])}
      {_metric("universe", counts["universe"])}
      {_metric("watching", watching)}
      {_metric("list window", list_window)}
      {_metric("gaps", counts["gaps"])}
      {_metric("intents", counts["intents"])}
      {_metric("rejects", counts["rejects"])}
      {_metric("fills", counts.get("fills", 0))}
      {_metric("completed pairs", completed_pairs)}
      {_metric("naked incidents", naked_incidents)}
      {_metric("paused", "yes" if paused else "no")}
      {_metric("runner", runner_alive)}
  </div>
  <div class="main">
    <section class="panel panel-watch">
      <h2>Closest book this hour</h2>
      {closest_html}
      <div class="watch-wrap">
        <h2>Watching now ({_esc(watching)})</h2>
        <p class="empty">{list_note}</p>
        {_watch_html(watch_rows)}
      </div>
    </section>
    <section class="panel panel-hist">
      <h2>Edge histogram (walked asks; thin is none)</h2>
      <p class="empty">considers {_esc(considers)} · hunt stays silent below min_edge 0.01</p>
      {_hist_bars_html(histogram)}
    </section>
    <section class="panel panel-logs">
      <div>
      <h2>Recent near-misses</h2>
      {_rows_html(summary.get("recent_nearmiss") or [], [
        ("raw_edge", "raw_edge"),
        ("fillable", "fillable"),
        ("in_watch", "in_watch"),
        ("thin", "thin"),
        ("age", "age"),
        ("condition_id", "condition_id"),
      ])}
      <h2>Paper alerts (not live orders)</h2>
      {_rows_html(summary.get("recent_alerts") or [], [
        ("path", "path"),
        ("size", "size"),
        ("raw_edge", "raw_edge"),
        ("expected_net_edge", "expected_net_edge"),
        ("outcome", "outcome"),
        ("condition_id", "condition_id"),
      ])}
      </div>
      <div>
      <h2>Reject reasons</h2>
      {_reason_bars_html(reasons)}
      <h2>Recent gaps</h2>
      {_rows_html(summary["recent_gaps"], [
        ("raw_edge", "raw_edge"),
        ("yes_vwap", "yes_vwap"),
        ("no_vwap", "no_vwap"),
        ("fillable", "fillable"),
        ("age", "age"),
        ("condition_id", "condition_id"),
      ])}
      <h2>Recent fills</h2>
      {_rows_html(summary.get("recent_fills") or [], [
        ("path", "path"),
        ("size", "size"),
        ("pnl", "pnl"),
        ("cost", "cost"),
        ("yes_vwap", "yes_vwap"),
        ("no_vwap", "no_vwap"),
        ("pair_fees", "pair_fees"),
      ])}
      <h2>Recent intents</h2>
      {_rows_html(summary["recent_intents"], [
        ("path", "path"),
        ("size", "size"),
        ("expected_net_edge", "expected_net_edge"),
      ])}
      </div>
    </section>
  </div>
  <footer>Paper $500 bankroll is not real money. Binds 127.0.0.1. Auto-refresh 2s. No live path.</footer>
  </div>
  <script>
    async function postControl(body) {{
      await fetch("/api/control", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify(body)
      }});
      location.reload();
    }}
    document.getElementById("btn-start").onclick = function () {{
      postControl({{action: "start"}});
    }};
    document.getElementById("btn-stop").onclick = function () {{
      postControl({{action: "stop"}});
    }};
    var slider = document.getElementById("rotate");
    var label = document.getElementById("rotate-val");
    slider.oninput = function () {{ label.textContent = slider.value + "s"; }};
    slider.onchange = function () {{
      postControl({{action: "rotate", rotate_s: Number(slider.value)}});
    }};
  </script>
</body>
</html>
"""


def make_handler(
    data_dir: Path,
    project_root: Path,
    *,
    spawn=None,
) -> type[BaseHTTPRequestHandler]:
    class PaperUIHandler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            summary = summarize_dashboard(data_dir, project_root=project_root)
            if path in ("/", "/index.html"):
                self._send(200, render_html(summary).encode("utf-8"), "text/html; charset=utf-8")
                return
            if path in ("/api/summary", "/api/summary.json"):
                payload = json.dumps(summary, separators=(",", ":")).encode("utf-8")
                self._send(200, payload, "application/json; charset=utf-8")
                return
            self._send(404, b"not found\n", "text/plain; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path != "/api/control":
                self._send(405, b"read-only\n", "text/plain; charset=utf-8")
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send(400, b"bad json\n", "text/plain; charset=utf-8")
                return
            if not isinstance(body, dict):
                self._send(400, b"bad json\n", "text/plain; charset=utf-8")
                return
            result = apply_control(
                data_dir,
                action=str(body.get("action") or ""),
                rotate_s=body.get("rotate_s"),
                project_root=project_root,
                spawn=spawn,
            )
            payload = json.dumps(result, separators=(",", ":")).encode("utf-8")
            self._send(200, payload, "application/json; charset=utf-8")

        def log_message(self, fmt: str, *args: object) -> None:
            sys.stderr.write("paper_ui: " + (fmt % args) + "\n")

    return PaperUIHandler


def serve(
    data_dir: Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    project_root: Path | None = None,
) -> int:
    root = Path(project_root) if project_root is not None else Path.cwd()
    handler = make_handler(data_dir, root)
    server = ThreadingHTTPServer((host, port), handler)
    bound_host, bound_port = server.server_address[:2]
    print(BANNER)
    print(f"paper_ui: http://{bound_host}:{bound_port}  data-dir={data_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\npaper_ui: stopped")
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only paper dashboard. Never places orders."
    )
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Bind address (default 127.0.0.1). Do not expose publicly.",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Where to look for HALT / data/state.sqlite (default cwd).",
    )
    parser.add_argument(
        "--place-orders",
        action="store_true",
        help="Rejected. This UI never places orders.",
    )
    args = parser.parse_args(argv)
    if args.place_orders:
        print("paper_ui: refuses to place orders", file=sys.stderr)
        return 2
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("paper_ui: bind 127.0.0.1 only (paper local watch)", file=sys.stderr)
        return 2
    return serve(
        Path(args.data_dir),
        host=args.host,
        port=args.port,
        project_root=Path(args.project_root),
    )


if __name__ == "__main__":
    raise SystemExit(main())
