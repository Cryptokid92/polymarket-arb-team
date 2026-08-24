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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BANNER = "PAPER MODE. Not live. Not financial advice."
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_DATA_DIR = "data/paper"
RECENT_LIMIT = 20
RUNNING_AGE_MS = 10_000
RECENT_AGE_MS = 60_000
LOG_NAMES = ("gaps.jsonl", "intents.jsonl", "rejects.jsonl", "stats.json")


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
    stats = read_stats_file(data_dir / "stats.json")

    jsonl_gaps = len(gaps)
    jsonl_intents = len(intents)
    jsonl_rejects = len(rejects)
    reasons = Counter(str(row.get("reason", "unknown")) for row in rejects)

    markets_listed = 0
    universe = 0
    if stats is not None:
        markets_listed = _int_or_zero(stats.get("markets_listed"))
        universe = _int_or_zero(stats.get("universe"))
        jsonl_gaps = max(jsonl_gaps, _int_or_zero(stats.get("gaps")))
        jsonl_intents = max(jsonl_intents, _int_or_zero(stats.get("intents")))
        jsonl_rejects = max(jsonl_rejects, _int_or_zero(stats.get("rejects")))
        extra = stats.get("reject_reasons")
        if isinstance(extra, dict) and not reasons:
            for key, value in extra.items():
                reasons[str(key)] += _int_or_zero(value)

    last_ts: int | None = None
    for rows in (gaps, intents, rejects):
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

    return {
        "banner": BANNER,
        "mode": "paper",
        "run_status": _infer_run_status(last_event_age_ms),
        "last_event_age_ms": last_event_age_ms,
        "last_log_mtime_ms": last_mtime,
        "heartbeat_ms": heartbeat_ms,
        "counts": {
            "markets_listed": markets_listed,
            "universe": universe,
            "gaps": jsonl_gaps,
            "intents": jsonl_intents,
            "rejects": jsonl_rejects,
        },
        "reject_reasons": dict(sorted(reasons.items())),
        "recent_gaps": _recent_gaps(gaps, recent_limit),
        "recent_intents": _recent_intents(intents, recent_limit),
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


def _rows_html(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return '<p class="empty">None yet. The runner has not written this log.</p>'
    head = "".join(f"<th>{_esc(title)}</th>" for title, _key in columns)
    body_parts: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(key))}</td>" for _title, key in columns)
        body_parts.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_parts)}</tbody></table>"


def render_html(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    halt = summary["halt"]
    reasons = summary["reject_reasons"]
    reason_rows = (
        "".join(
            f"<tr><td>{_esc(reason)}</td><td>{_esc(count)}</td></tr>"
            for reason, count in reasons.items()
        )
        if reasons
        else '<tr><td colspan="2" class="empty">None</td></tr>'
    )
    halt_class = "halted" if halt.get("halted") else "ok"
    halt_label = "HALTED" if halt.get("halted") else "not halted"
    sources = ", ".join(halt.get("sources") or ()) or "none"
    sqlite_bit = "yes" if halt.get("sqlite_exists") else "no"
    halt_file_bit = "yes" if halt.get("halt_file") else "no"
    halt_reason = halt.get("halt_reason") or "none"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Paper dashboard — completeness arb</title>
  <meta name="robots" content="noindex">
  <meta http-equiv="refresh" content="2">
  <style>
    :root {{ color-scheme: dark; }}
    body {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
           margin: 0; background: #111; color: #eee; }}
    header {{ background: #4a3b00; color: #ffe08a; padding: 12px 16px;
              border-bottom: 3px solid #e6c15a; font-weight: 700; }}
    main {{ padding: 16px; max-width: 1100px; }}
    h2 {{ margin: 20px 0 8px; font-size: 14px; letter-spacing: 0.04em;
          text-transform: uppercase; color: #9ad; }}
    .grid {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }}
    .card {{ background: #1b1b1b; border: 1px solid #333; padding: 10px; }}
    .card .n {{ font-size: 28px; }}
    .status {{ margin: 12px 0; }}
    .ok {{ color: #8d8; }}
    .halted {{ color: #f88; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; background: #1b1b1b; }}
    th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #333; }}
    th {{ color: #aaa; font-weight: 600; }}
    .empty {{ color: #888; }}
    footer {{ color: #777; padding: 16px; font-size: 12px; }}
  </style>
</head>
<body>
  <header>{_esc(summary["banner"])}</header>
  <main>
    <div class="status">
      Run status: <strong>{_esc(summary["run_status"])}</strong>
      · last event {_esc(_age_label(summary.get("last_event_age_ms")))}
      · halt: <span class="{halt_class}">{halt_label}</span>
      · halt reason: {_esc(halt_reason)}
      · HALT file: {halt_file_bit}
      · sqlite: {sqlite_bit}
      · sources: {_esc(sources)}
    </div>
    <h2>Counts</h2>
    <div class="grid">
      <div class="card">markets listed<div class="n">{_esc(counts["markets_listed"])}</div></div>
      <div class="card">universe<div class="n">{_esc(counts["universe"])}</div></div>
      <div class="card">gaps<div class="n">{_esc(counts["gaps"])}</div></div>
      <div class="card">intents<div class="n">{_esc(counts["intents"])}</div></div>
      <div class="card">rejects<div class="n">{_esc(counts["rejects"])}</div></div>
    </div>
    <h2>Reject reasons</h2>
    <table><thead><tr><th>reason</th><th>count</th></tr></thead>
    <tbody>{reason_rows}</tbody></table>
    <h2>Recent gaps</h2>
    {_rows_html(summary["recent_gaps"], [
        ("raw_edge", "raw_edge"),
        ("yes_vwap", "yes_vwap"),
        ("no_vwap", "no_vwap"),
        ("fillable", "fillable"),
        ("age", "age"),
        ("condition_id", "condition_id"),
    ])}
    <h2>Recent intents</h2>
    {_rows_html(summary["recent_intents"], [
        ("path", "path"),
        ("size", "size"),
        ("expected_net_edge", "expected_net_edge"),
    ])}
  </main>
  <footer>Read-only. Binds 127.0.0.1. Auto-refresh 2s. No orders. No live path.</footer>
</body>
</html>
"""


def make_handler(data_dir: Path, project_root: Path) -> type[BaseHTTPRequestHandler]:
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
            self._send(405, b"read-only\n", "text/plain; charset=utf-8")

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
