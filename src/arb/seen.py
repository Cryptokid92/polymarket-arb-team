"""Unique markets the paper runner has listed or walked. Not a trade."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SEEN_FILENAME = "seen_markets.json"


class SeenMarkets:
    """In-memory unique condition ids. Persist under the data dir only."""

    def __init__(self) -> None:
        self.listed: set[str] = set()
        self.universe: set[str] = set()
        self.walked: set[str] = set()

    def note_listed(self, condition_id: object) -> None:
        cid = _cid(condition_id)
        if cid:
            self.listed.add(cid)

    def note_universe(self, condition_id: object) -> None:
        cid = _cid(condition_id)
        if cid:
            self.listed.add(cid)
            self.universe.add(cid)

    def note_walked(self, condition_id: object) -> None:
        cid = _cid(condition_id)
        if cid:
            self.listed.add(cid)
            self.walked.add(cid)

    @property
    def listed_unique(self) -> int:
        return len(self.listed)

    @property
    def universe_unique(self) -> int:
        return len(self.universe)

    @property
    def walked_unique(self) -> int:
        return len(self.walked)

    def apply_to(self, stats: Any) -> None:
        stats.listed_unique = self.listed_unique
        stats.universe_unique = self.universe_unique
        stats.walked_unique = self.walked_unique

    def save(self, data_dir: Path) -> None:
        path = Path(data_dir) / SEEN_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "listed": sorted(self.listed),
            "universe": sorted(self.universe),
            "walked": sorted(self.walked),
        }
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        tmp.replace(path)


def _cid(value: object) -> str:
    return str(value or "").strip()


def load_seen_markets(data_dir: Path) -> SeenMarkets:
    seen = SeenMarkets()
    path = Path(data_dir) / SEEN_FILENAME
    if path.is_file():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            for raw in parsed.get("listed") or ():
                seen.note_listed(raw)
            for raw in parsed.get("universe") or ():
                seen.note_universe(raw)
            for raw in parsed.get("walked") or ():
                seen.note_walked(raw)
    _backfill_jsonl(seen, Path(data_dir) / "rejects.jsonl", walked=False)
    _backfill_jsonl(seen, Path(data_dir) / "nearmiss.jsonl", walked=True)
    return seen


def _backfill_jsonl(seen: SeenMarkets, path: Path, *, walked: bool) -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        cid = row.get("condition_id")
        if walked:
            seen.note_walked(cid)
        else:
            seen.note_listed(cid)
