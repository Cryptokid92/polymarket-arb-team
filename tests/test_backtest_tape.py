"""CLI for hour-tape replay. Paper only."""

from __future__ import annotations

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


def test_backtest_tape_refuses_orders_and_missing_tape(tmp_path: Path) -> None:
    module = _load_script()
    assert module.main(["--place-orders"]) == 2
    source = Path("scripts/backtest_tape.py").read_text(encoding="utf-8")
    assert "AsyncSecureClient" not in source
    assert module.main(["--tape", str(tmp_path / "missing.jsonl")]) == 0


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