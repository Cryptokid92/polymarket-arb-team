from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import threading
from http.client import HTTPConnection
from decimal import Decimal
from pathlib import Path

from arb.app import PaperRunStats, write_paper_stats

FIXTURES = Path(__file__).parent / "fixtures" / "paper_ui"
FIXTURE_LAST_TS_MS = 1_700_000_001_500


def _utime_ms(path: Path, ts_ms: int) -> None:
    ns = ts_ms * 1_000_000
    os.utime(path, ns=(ns, ns))


def _copy_fixtures(tmp_path: Path, *, mtime_ms: int) -> Path:
    dest = tmp_path / "paper_ui"
    shutil.copytree(FIXTURES, dest)
    for name in ("gaps.jsonl", "intents.jsonl", "rejects.jsonl", "stats.json"):
        path = dest / name
        if path.is_file():
            _utime_ms(path, mtime_ms)
    return dest


def _load_script():
    spec = importlib.util.spec_from_file_location("paper_ui_cli", Path("scripts/paper_ui.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summarize_fixture_counts(tmp_path: Path) -> None:
    ui = _load_script()
    paper = _copy_fixtures(tmp_path, mtime_ms=FIXTURE_LAST_TS_MS)
    summary = ui.summarize_dashboard(
        paper,
        project_root=paper,
        now_ms=FIXTURE_LAST_TS_MS + 120_000,
    )
    assert summary["banner"] == "PAPER MODE. Not live. Not financial advice."
    assert summary["mode"] == "paper"
    assert summary["counts"] == {
        "markets_listed": 10,
        "universe": 6,
        "gaps": 2,
        "intents": 2,
        "rejects": 4,
        "fills": 0,
    }
    assert summary["paper"]["bankroll"] == "500"
    assert summary["paper"]["daily_pnl"] == "0"
    assert summary["recent_fills"] == []
    assert summary["control"]["rotate_s"] == 1
    assert summary["reject_reasons"] == {
        "neg_risk": 1,
        "short_crypto_window": 1,
        "stale": 2,
    }
    gaps = summary["recent_gaps"]
    assert len(gaps) == 2
    assert gaps[0]["raw_edge"] == "0.02"
    assert gaps[0]["yes_vwap"] == "0.50"
    assert gaps[0]["no_vwap"] == "0.48"
    assert gaps[0]["fillable"] == "10"
    assert gaps[0]["age"] == 80
    intents = summary["recent_intents"]
    assert [row["path"] for row in intents] == ["taker_fak", "maker_gtc"]
    assert intents[0]["size"] == "8"
    assert intents[0]["expected_net_edge"] == "0.12"
    assert summary["halt"]["halted"] is False
    assert summary["run_status"] == "stale"
    assert summary["last_event_age_ms"] == 120_000


def test_dashboard_shows_closest_and_alerts(tmp_path: Path) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    write_paper_stats(
        paper / "stats.json",
        PaperRunStats(
            markets_listed=4,
            universe=2,
            best_edge=Decimal("0"),
            closest_condition_id="c-flat",
            closest_fillable=Decimal("50"),
            closest_book_age_ms=80,
            closest_in_watch=True,
            closest_thin=False,
            nearmiss_considers=3,
            edge_histogram={"0_0.005": 2, "none": 1},
            completed_pairs=1,
            naked_incidents=1,
            alerts=1,
        ),
        now_ms=1_700_000_000_500,
    )
    (paper / "nearmiss.jsonl").write_text(
        json.dumps(
            {
                "ts_ms": 1_700_000_000_400,
                "condition_id": "c-flat",
                "raw_edge": "0",
                "fillable_shares": "50",
                "in_watch": True,
                "thin": False,
                "book_age_ms": 80,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (paper / "alerts.jsonl").write_text(
        json.dumps(
            {
                "ts_ms": 1_700_000_000_400,
                "path": "maker_gtc",
                "size": "10",
                "raw_edge": "0.03",
                "expected_net_edge": "0.30",
                "outcome": "filled",
                "condition_id": "c-gap",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=1_700_000_000_500)
    assert summary["best_edge"] == "0"
    assert summary["closest"]["condition_id"] == "c-flat"
    assert summary["paper"]["completed_pairs"] == 1
    assert summary["paper"]["naked_incidents"] == 1
    assert summary["recent_nearmiss"][0]["raw_edge"] == "0"
    assert summary["recent_alerts"][0]["outcome"] == "filled"
    page = ui.render_html(summary)
    assert "Closest book this hour" in page
    assert "c-flat" in page
    assert "Paper alerts" in page


def test_missing_logs_are_zeros_not_invented(tmp_path: Path) -> None:
    ui = _load_script()
    empty = tmp_path / "paper"
    empty.mkdir()
    summary = ui.summarize_dashboard(empty, project_root=tmp_path, now_ms=1)
    assert summary["counts"] == {
        "markets_listed": 0,
        "universe": 0,
        "gaps": 0,
        "intents": 0,
        "rejects": 0,
        "fills": 0,
    }
    assert summary["reject_reasons"] == {}
    assert summary["recent_gaps"] == []
    assert summary["recent_intents"] == []
    assert summary["recent_fills"] == []
    assert summary["paper"]["bankroll"] == "500"
    assert summary["paper"]["daily_pnl"] == "0"
    assert summary["run_status"] == "no_data"
    assert summary["heartbeat_ms"] is None
    assert summary["halt"]["halted"] is False


def test_jsonl_only_counts_without_stats(tmp_path: Path) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "gaps.jsonl").write_text(
        '{"raw_edge":"0.03","yes_vwap":"0.55","no_vwap":"0.42","fillable_shares":"5","book_age_ms":3}\n',
        encoding="utf-8",
    )
    (paper / "intents.jsonl").write_text(
        '{"path":"maker_gtc","size":"5","expected_net_edge":"0.15"}\n',
        encoding="utf-8",
    )
    (paper / "rejects.jsonl").write_text('{"reason":"stale"}\n{"reason":"stale"}\n', encoding="utf-8")
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=1)
    assert summary["counts"]["markets_listed"] == 0
    assert summary["counts"]["universe"] == 0
    assert summary["counts"]["gaps"] == 1
    assert summary["counts"]["intents"] == 1
    assert summary["counts"]["rejects"] == 2
    assert summary["reject_reasons"] == {"stale": 2}


def test_halt_file_is_read_only(tmp_path: Path) -> None:
    ui = _load_script()
    (tmp_path / "HALT").write_text("stop\n", encoding="utf-8")
    summary = ui.summarize_dashboard(tmp_path / "paper", project_root=tmp_path, now_ms=1)
    assert summary["halt"]["halt_file"] is True
    assert summary["halt"]["halted"] is True
    assert (tmp_path / "HALT").is_file()


def test_halt_from_readonly_sqlite(tmp_path: Path) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    db = paper / "state.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta(key, value) VALUES ('halted', '1')")
    conn.execute("INSERT INTO meta(key, value) VALUES ('halt_reason', 'ws_stale')")
    conn.commit()
    conn.close()
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=1)
    assert summary["halt"]["sqlite_exists"] is True
    assert summary["halt"]["sqlite_halted"] is True
    assert summary["halt"]["halted"] is True
    assert summary["halt"]["halt_reason"] == "ws_stale"
    page = ui.render_html(summary)
    assert "ws_stale" in page
    assert "stream or REST probe failed" in page
    assert "not daily loss" in page


def test_html_banner_and_refresh() -> None:
    ui = _load_script()
    summary = ui.summarize_dashboard(
        FIXTURES, project_root=FIXTURES, now_ms=1_700_000_002_000
    )
    page = ui.render_html(summary)
    assert "PAPER MODE. Not live. Not financial advice." in page
    assert 'http-equiv="refresh" content="2"' in page
    assert "maker_gtc" in page
    assert "taker_fak" in page
    assert "0.03" in page
    assert "paper bankroll" in page
    assert "btn-start" in page
    assert "btn-stop" in page
    assert "Watch rotate" in page
    assert "not real money" in page.lower() or "Not real money" in page


def test_http_is_readonly_and_local() -> None:
    ui = _load_script()
    handler = ui.make_handler(FIXTURES, FIXTURES)
    server = ui.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        assert host == "127.0.0.1"
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/api/summary")
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert payload["counts"]["markets_listed"] == 10
        assert payload["counts"]["gaps"] == 2
        conn.close()

        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/")
        home = conn.getresponse()
        body = home.read().decode("utf-8")
        assert home.status == 200
        assert "PAPER MODE" in body
        conn.close()

        conn = HTTPConnection(host, port, timeout=2)
        conn.request("POST", "/api/summary", body="{}", headers={"Content-Type": "application/json"})
        posted = conn.getresponse()
        assert posted.status == 405
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_cli_refuses_place_orders_and_non_loopback() -> None:
    ui = _load_script()
    assert ui.main(["--place-orders"]) == 2
    assert ui.main(["--host", "0.0.0.0"]) == 2


def test_source_stays_paper_only() -> None:
    source = Path("scripts/paper_ui.py").read_text(encoding="utf-8")
    assert "AsyncSecureClient" not in source
    assert "ALLOW_LIVE" not in source
    assert "from polymarket" not in source
    assert "http.server" in source


def test_write_paper_stats_has_no_account_fields(tmp_path: Path) -> None:
    stats = PaperRunStats(markets_listed=7, universe=3, gaps=1, intents=1, rejects={"stale": 2})
    path = tmp_path / "stats.json"
    write_paper_stats(path, stats, now_ms=1_700_000_000_123)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "markets_listed": 7,
        "universe": 3,
        "gaps": 1,
        "intents": 1,
        "rejects": 2,
        "reject_reasons": {"stale": 2},
        "watching": 0,
        "bankroll": "500",
        "daily_pnl": "0",
        "fills": 0,
        "completed_pairs": 0,
        "naked_incidents": 0,
        "alerts": 0,
        "best_edge": None,
        "closest_condition_id": None,
        "closest_fillable": None,
        "closest_book_age_ms": None,
        "closest_in_watch": None,
        "closest_thin": None,
        "nearmiss_considers": 0,
        "edge_histogram": {},
        "watch": [],
        "list_window": 1,
        "list_cursor": None,
        "list_wraps": 0,
        "list_next_queued": False,
        "list_window_s": 60,
        "list_hold_s": 0,
        "listed_unique": 0,
        "universe_unique": 0,
        "walked_unique": 0,
        "heartbeat_ms": 1_700_000_000_123,
    }
    blob = path.read_text(encoding="utf-8")
    for banned in ("private_key", "wallet", "secret", "api_key", "ALLOW_LIVE"):
        assert banned not in blob


def test_fresh_stats_mtime_is_running_despite_old_rejects(tmp_path: Path) -> None:
    """Hour-5: opening rejects are old; runner is still rewriting stats.json."""
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    old_ts = 1_700_000_000_000
    now_ms = old_ts + 11 * 60 * 1000
    (paper / "rejects.jsonl").write_text(
        json.dumps({"ts_ms": old_ts, "reason": "neg_risk"}) + "\n",
        encoding="utf-8",
    )
    (paper / "stats.json").write_text(
        json.dumps(
            {
                "markets_listed": 80,
                "universe": 2,
                "gaps": 0,
                "intents": 0,
                "rejects": 78,
                "reject_reasons": {"neg_risk": 78},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _utime_ms(paper / "rejects.jsonl", old_ts)
    _utime_ms(paper / "stats.json", now_ms - 3_000)
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=now_ms)
    assert summary["run_status"] == "running"
    assert summary["last_event_age_ms"] == 3_000
    assert summary["halt"]["halted"] is False
    assert summary["halt"]["halt_reason"] is None


def test_stats_heartbeat_field_counts_as_event(tmp_path: Path) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    old_ts = 1_700_000_000_000
    now_ms = old_ts + 11 * 60 * 1000
    heartbeat_ms = now_ms - 5_000
    (paper / "rejects.jsonl").write_text(
        json.dumps({"ts_ms": old_ts, "reason": "neg_risk"}) + "\n",
        encoding="utf-8",
    )
    (paper / "stats.json").write_text(
        json.dumps(
            {
                "markets_listed": 80,
                "universe": 2,
                "gaps": 0,
                "intents": 0,
                "rejects": 78,
                "reject_reasons": {"neg_risk": 78},
                "heartbeat_ms": heartbeat_ms,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _utime_ms(paper / "rejects.jsonl", old_ts)
    _utime_ms(paper / "stats.json", old_ts)
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=now_ms)
    assert summary["run_status"] == "running"
    assert summary["last_event_age_ms"] == 5_000
    assert summary["heartbeat_ms"] == heartbeat_ms
    assert summary["halt"]["halted"] is False


def test_stale_logs_do_not_invent_halt(tmp_path: Path) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    old_ts = 1_700_000_000_000
    now_ms = old_ts + 11 * 60 * 1000
    (paper / "rejects.jsonl").write_text(
        json.dumps({"ts_ms": old_ts, "reason": "neg_risk"}) + "\n",
        encoding="utf-8",
    )
    (paper / "stats.json").write_text(
        json.dumps(
            {
                "markets_listed": 80,
                "universe": 2,
                "gaps": 0,
                "intents": 0,
                "rejects": 78,
                "reject_reasons": {"neg_risk": 78},
                "heartbeat_ms": old_ts,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _utime_ms(paper / "rejects.jsonl", old_ts)
    _utime_ms(paper / "stats.json", old_ts)
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=now_ms)
    assert summary["run_status"] == "stale"
    assert summary["last_event_age_ms"] == 11 * 60 * 1000
    assert summary["halt"]["halted"] is False
    assert summary["halt"]["halt_reason"] is None
    page = ui.render_html(summary)
    assert "stale" in page
    assert "not halted" in page
    assert "HALTED" not in page


def test_halt_file_still_wins_when_stats_are_fresh(tmp_path: Path) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    now_ms = 1_700_000_660_000
    (tmp_path / "HALT").write_text("stop\n", encoding="utf-8")
    write_paper_stats(
        paper / "stats.json",
        PaperRunStats(markets_listed=80, universe=2),
        now_ms=now_ms - 2_000,
    )
    _utime_ms(paper / "stats.json", now_ms - 2_000)
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=now_ms)
    assert summary["run_status"] == "running"
    assert summary["last_event_age_ms"] == 2_000
    assert summary["halt"]["halted"] is True
    assert summary["halt"]["halt_file"] is True


def test_dashboard_reads_bankroll_pnl_and_fills(tmp_path: Path) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    write_paper_stats(
        paper / "stats.json",
        PaperRunStats(
            markets_listed=4,
            universe=2,
            gaps=1,
            intents=1,
            bankroll=Decimal("500.30"),
            daily_pnl=Decimal("0.30"),
            fills=1,
        ),
        now_ms=1_700_000_000_500,
    )
    (paper / "fills.jsonl").write_text(
        json.dumps(
            {
                "ts_ms": 1_700_000_000_400,
                "path": "maker_gtc",
                "size": "10",
                "yes_vwap": "0.55",
                "no_vwap": "0.42",
                "pair_fees": "0",
                "cost": "9.70",
                "pnl": "0.30",
                "bankroll": "500.30",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=1_700_000_000_500)
    assert summary["paper"]["bankroll"] == "500.30"
    assert summary["paper"]["daily_pnl"] == "0.30"
    assert summary["counts"]["fills"] == 1
    assert summary["recent_fills"][0]["pnl"] == "0.30"
    page = ui.render_html(summary)
    assert "500.30" in page
    assert "earned" in page


def test_html_uses_fullscreen_board_and_histogram_bars(tmp_path: Path) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    write_paper_stats(
        paper / "stats.json",
        PaperRunStats(
            markets_listed=80,
            universe=12,
            watching=40,
            nearmiss_considers=9,
            listed_unique=9000,
            universe_unique=2100,
            walked_unique=800,
            best_edge=Decimal("-0.001"),
            closest_condition_id="c-near",
            closest_fillable=Decimal("5"),
            closest_book_age_ms=80,
            closest_in_watch=False,
            edge_histogram={"lt_-0.05": 8, "-0.01_0": 1, "none": 0},
            watch=[
                {
                    "condition_id": "c-hot",
                    "label": "Will it rain?",
                    "pinned": True,
                    "raw_edge": "-0.001",
                },
                {
                    "condition_id": "c-rot",
                    "label": "rotating-market",
                    "pinned": False,
                    "raw_edge": None,
                },
            ],
        ),
        now_ms=1_700_000_000_500,
    )
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=1_700_000_000_500)
    assert summary["paper"]["watching"] == 40
    assert summary["paper"]["nearmiss_considers"] == 9
    assert summary["paper"]["watch"][0]["label"] == "Will it rain?"
    page = ui.render_html(summary)
    assert "Watching now" in page
    assert "list window" in page
    assert "unique listed" in page
    assert "unique walked" in page
    assert "next 5000 every" in page
    assert "next 5000 in" in page
    assert "Different markets gone through" in page
    assert "9000" in page
    assert "800" in page
    assert summary["paper"]["listed_unique"] == 9000
    assert summary["paper"]["walked_unique"] == 800
    assert "Will it rain?" in page
    assert "c-hot" in page
    assert "c-rot" in page
    assert 'class="watch-kind">pin' in page
    assert 'class="watch-kind">rot' in page
    assert "panel-watch" in page
    assert "grid-row: 1 / span 2" in page
    assert "panel-logs" in page
    assert 'class="board"' in page
    assert "100vh" in page
    assert "data-bucket=" in page
    assert "lt_-0.05" in page
    assert "c-near" in page
    assert "Closest book this hour" in page
    assert "not halted" in page
    assert "HALTED" not in page


def test_coverage_html_uses_unique_listed_as_scale() -> None:
    ui = _load_script()
    html = ui._coverage_html(
        listed_unique=100,
        universe_unique=40,
        walked_unique=10,
        window_listed=50,
    )
    assert "Different markets gone through" in html
    assert 'data-bucket="listed_unique"' in html
    assert 'data-bucket="walked_unique"' in html
    assert ">100<" in html or ">100</span>" in html
    empty = ui._coverage_html(
        listed_unique=0, universe_unique=0, walked_unique=0, window_listed=0
    )
    assert "No unique markets yet" in empty


def test_list_note_explains_walked_plateau_while_next_window_lists(
    tmp_path: Path,
) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    write_paper_stats(
        paper / "stats.json",
        PaperRunStats(
            markets_listed=5000,
            universe=925,
            listed_unique=11896,
            universe_unique=925,
            walked_unique=944,
            list_window=3,
            list_next_queued=True,
        ),
        now_ms=1_700_000_000_500,
    )
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=1_700_000_000_500)
    page = ui.render_html(summary)
    assert "waiting on next list pages" in page
    assert "944" in page


def test_http_control_stop_and_slider(tmp_path: Path) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    spawned: list[tuple[object, object]] = []

    def spawn(root, data_dir) -> None:
        spawned.append((root, data_dir))

    handler = ui.make_handler(paper, tmp_path, spawn=spawn)
    server = ui.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            "/api/control",
            body=json.dumps({"action": "stop"}),
            headers={"Content-Type": "application/json"},
        )
        stopped = json.loads(conn.getresponse().read().decode("utf-8"))
        conn.close()
        assert stopped["ok"] is True
        assert stopped["paused"] is True
        assert spawned == []

        conn = HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            "/api/control",
            body=json.dumps({"action": "rotate", "rotate_s": 30}),
            headers={"Content-Type": "application/json"},
        )
        rotated = json.loads(conn.getresponse().read().decode("utf-8"))
        conn.close()
        assert rotated["ok"] is True
        assert rotated["rotate_s"] == 30
        control = json.loads((paper / "control.json").read_text(encoding="utf-8"))
        assert control["rotate_s"] == 30
        assert "stale_ms" not in control

        conn = HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            "/api/control",
            body=json.dumps({"action": "start"}),
            headers={"Content-Type": "application/json"},
        )
        started = json.loads(conn.getresponse().read().decode("utf-8"))
        conn.close()
        assert started["ok"] is True
        assert started["paused"] is False
        assert started["started"] is True
        assert spawned == [(tmp_path, paper)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_paused_control_sets_run_status(tmp_path: Path) -> None:
    ui = _load_script()
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "control.json").write_text('{"paused": true, "rotate_s": 20}\n', encoding="utf-8")
    write_paper_stats(paper / "stats.json", PaperRunStats(), now_ms=1_700_000_000_100)
    summary = ui.summarize_dashboard(paper, project_root=tmp_path, now_ms=1_700_000_000_200)
    assert summary["run_status"] == "paused"
    assert summary["control"]["rotate_s"] == 20
