"""CLI for hour-tape replay. Paper only. Fail closed."""

from __future__ import annotations

import json
from pathlib import Path

from arb.backtest import analyze_tape_edges, replay_tape_path, summarize_tape
from arb.recorder import load_jsonl


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "backtest_tape_cli", Path("scripts/backtest_tape.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _quiet_complete_ask_events() -> list[dict]:
    """Still-at-bid complete book. Shown-take engine completes 0 pairs."""
    rows: list[dict] = []
    for ts in (1000, 1400, 1800):
        for side, token, bid, ask in (
            ("YES", "yes-flat", "0.49", "0.50"),
            ("NO", "no-flat", "0.49", "0.50"),
        ):
            rows.append(
                {
                    "event_type": "book",
                    "ts_ms": ts,
                    "timestamp": str(ts),
                    "condition_id": "syn-flat",
                    "asset_id": token,
                    "market_side": side,
                    "tick_size": "0.01",
                    "min_order_size": "5",
                    "bids": [{"price": bid, "size": "20"}],
                    "asks": [{"price": ask, "size": "50"}],
                }
            )
    return rows


def test_backtest_tape_refuses_orders_and_missing_tape(
    tmp_path: Path, capsys
) -> None:
    module = _load_script()
    assert module.main(["--place-orders"]) == 2
    source = Path("scripts/backtest_tape.py").read_text(encoding="utf-8")
    assert "AsyncSecureClient" not in source
    assert module.main(["--tape", str(tmp_path / "missing.jsonl")]) == 1
    out = capsys.readouterr().out
    assert "verdict: no_tape" in out
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert module.main(["--tape", str(empty)]) == 1
    out = capsys.readouterr().out
    assert "verdict: no_tape" in out


def test_backtest_tape_replays_fixture(capsys) -> None:
    module = _load_script()
    tape = Path("tests/fixtures/recorded/gap_persist.jsonl")
    assert module.main(["--tape", str(tape)]) == 0
    out = capsys.readouterr().out
    assert "verdict: positive" in out
    assert "decision: capture" in out
    events = load_jsonl(tape)
    assert summarize_tape(events)["verdict"] == "positive"
    assert analyze_tape_edges(events)["decision"] == "capture"
    streamed_edges, streamed_tape = replay_tape_path(tape)
    assert streamed_tape["verdict"] == "positive"
    assert streamed_edges["decision"] == "capture"
    assert streamed_tape["events"] == len(events)
    assert streamed_tape["completed_pairs"] == summarize_tape(events)["completed_pairs"]


def test_backtest_tape_fails_closed_on_non_positive(
    tmp_path: Path, capsys
) -> None:
    tape = tmp_path / "quiet_book.jsonl"
    with tape.open("w", encoding="utf-8") as handle:
        for row in _quiet_complete_ask_events():
            handle.write(json.dumps(row) + "\n")
    events = load_jsonl(tape)
    assert summarize_tape(events)["verdict"] == "non_positive"
    assert summarize_tape(events)["completed_pairs"] == 0
    module = _load_script()
    assert module.main(["--tape", str(tape)]) == 1
    out = capsys.readouterr().out
    assert "verdict: non_positive" in out
    assert "stop: net EV is not positive. Do not loosen risk. Do not go live." in out
