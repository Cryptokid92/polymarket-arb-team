"""Unique listed/walked markets. Does not raise LIST_SAFETY_CAP."""

from __future__ import annotations

import json
from pathlib import Path

from arb.app import PaperRunStats
from arb.seen import SeenMarkets, load_seen_markets


def test_unique_counts_ignore_blanks_and_duplicates() -> None:
    seen = SeenMarkets()
    seen.note_listed("a")
    seen.note_listed("a")
    seen.note_listed("")
    seen.note_listed(None)
    seen.note_universe("b")
    seen.note_walked("b")
    seen.note_walked("c")
    assert seen.listed_unique == 3
    assert seen.universe_unique == 1
    assert seen.walked_unique == 2


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    seen = SeenMarkets()
    seen.note_listed("listed-only")
    seen.note_universe("kept")
    seen.note_walked("walked")
    seen.save(tmp_path)
    loaded = load_seen_markets(tmp_path)
    assert loaded.listed == {"listed-only", "kept", "walked"}
    assert loaded.universe == {"kept"}
    assert loaded.walked == {"walked"}


def test_backfill_rejects_and_nearmiss(tmp_path: Path) -> None:
    (tmp_path / "rejects.jsonl").write_text(
        json.dumps({"condition_id": "rej-1", "reason": "neg_risk"}) + "\n"
        + json.dumps({"condition_id": "rej-1", "reason": "neg_risk"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "nearmiss.jsonl").write_text(
        json.dumps({"condition_id": "walk-1", "raw_edge": "-0.01"}) + "\n",
        encoding="utf-8",
    )
    loaded = load_seen_markets(tmp_path)
    assert "rej-1" in loaded.listed
    assert "walk-1" in loaded.listed
    assert "walk-1" in loaded.walked
    assert loaded.listed_unique == 2
    assert loaded.walked_unique == 1


def test_apply_to_stats_writes_counts() -> None:
    seen = SeenMarkets()
    seen.note_listed("a")
    seen.note_universe("b")
    seen.note_walked("c")
    stats = PaperRunStats()
    seen.apply_to(stats)
    assert stats.listed_unique == 3
    assert stats.universe_unique == 1
    assert stats.walked_unique == 1
