from __future__ import annotations

import importlib.util
import json
import sqlite3
import threading
from http.client import HTTPConnection
from pathlib import Path

from arb.app import PaperRunStats, write_paper_stats

FIXTURES = Path(__file__).parent / "fixtures" / "paper_ui"


def _load_script():
    spec = importlib.util.spec_from_file_location("paper_ui_cli", Path("scripts/paper_ui.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summarize_fixture_counts() -> None:
    ui = _load_script()
    summary = ui.summarize_dashboard(
        FIXTURES,
        project_root=FIXTURES,
        now_ms=1_700_000_001_500 + 120_000,
    )
    assert summary["banner"] == "PAPER MODE. Not live. Not financial advice."
    assert summary["mode"] == "paper"
    assert summary["counts"] == {
        "markets_listed": 10,
        "universe": 6,
        "gaps": 2,
        "intents": 2,
        "rejects": 4,
    }
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
    }
    assert summary["reject_reasons"] == {}
    assert summary["recent_gaps"] == []
    assert summary["recent_intents"] == []
    assert summary["run_status"] == "no_data"
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
    write_paper_stats(path, stats)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "markets_listed": 7,
        "universe": 3,
        "gaps": 1,
        "intents": 1,
        "rejects": 2,
        "reject_reasons": {"stale": 2},
    }
    blob = path.read_text(encoding="utf-8")
    for banned in ("private_key", "wallet", "secret", "api_key", "ALLOW_LIVE"):
        assert banned not in blob
