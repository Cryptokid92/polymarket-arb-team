"""Local pause/resume and watch-rotate slider. Paper only."""

from __future__ import annotations

import inspect
import json
from decimal import Decimal
from pathlib import Path

from arb.app import WATCH_PAIRS, WATCH_ROTATE_S
from arb.config import Settings, _EnvSettings
from arb.killswitch import KillSwitch
from arb.money import d
from arb.paper_control import (
    ROTATE_DEFAULT_S,
    ROTATE_MAX_S,
    ROTATE_MIN_S,
    apply_control,
    clamp_rotate_s,
    default_spawn,
    effective_rotate_s,
    read_control,
    resume_paper_halt,
    runner_is_alive,
    write_control,
    write_pid,
)
from arb.state import StateStore


def test_rotate_defaults_match_watch_slice() -> None:
    assert ROTATE_DEFAULT_S == WATCH_ROTATE_S == 1
    assert ROTATE_MIN_S == 1
    assert ROTATE_MAX_S == 120
    assert WATCH_PAIRS == 100


def test_clamp_rotate_s_is_1_to_120() -> None:
    assert clamp_rotate_s(1) == 1
    assert clamp_rotate_s(10) == 10
    assert clamp_rotate_s(120) == 120
    assert clamp_rotate_s(90) == 90
    assert clamp_rotate_s(0) == 1
    assert clamp_rotate_s(121) == 120
    assert clamp_rotate_s("45") == 45
    assert clamp_rotate_s("nope") == 1


def test_slider_write_persists_rotate_s(tmp_path: Path) -> None:
    result = apply_control(tmp_path, action="rotate", rotate_s=45)
    assert result["ok"] is True
    assert result["rotate_s"] == 45
    assert result["paused"] is False
    control = read_control(tmp_path)
    assert control.rotate_s == 45
    payload = json.loads((tmp_path / "control.json").read_text(encoding="utf-8"))
    assert payload == {"paused": False, "rotate_s": 45}
    assert "stale_ms" not in payload
    assert "min_edge" not in payload
    assert "max_gap" not in payload
    assert "paper_bankroll" not in payload


def test_slider_write_does_not_loosen_caps() -> None:
    fields = _EnvSettings.model_fields
    assert fields["stale_ms"].default == 400
    assert fields["min_edge"].default == Decimal("0.01")
    assert fields["max_gap"].default == Decimal("0.08")
    assert fields["max_notional_per_trade"].default == Decimal("25")
    assert fields["max_daily_loss"].default == Decimal("50")
    assert fields["max_open_pairs"].default == 3
    assert fields["paper_bankroll"].default == Decimal("500")
    assert WATCH_ROTATE_S == 1
    assert WATCH_PAIRS == 100


def test_stop_pauses_without_spawning(tmp_path: Path) -> None:
    spawned: list[tuple[Path, Path]] = []

    def spawn(root: Path, data_dir: Path) -> None:
        spawned.append((root, data_dir))

    result = apply_control(
        tmp_path, action="stop", project_root=tmp_path, spawn=spawn
    )
    assert result["ok"] is True
    assert result["paused"] is True
    assert result["started"] is False
    assert spawned == []
    assert read_control(tmp_path).paused is True


def test_start_resumes_when_runner_alive(tmp_path: Path) -> None:
    write_pid(tmp_path)
    apply_control(tmp_path, action="stop")
    spawned: list[tuple[Path, Path]] = []

    def spawn(root: Path, data_dir: Path) -> None:
        spawned.append((root, data_dir))

    result = apply_control(
        tmp_path, action="start", project_root=tmp_path, spawn=spawn
    )
    assert result["ok"] is True
    assert result["paused"] is False
    assert result["started"] is False
    assert spawned == []
    assert runner_is_alive(tmp_path) is True


def test_start_execs_paper_run_when_none_up(tmp_path: Path) -> None:
    spawned: list[tuple[Path, Path]] = []

    def spawn(root: Path, data_dir: Path) -> None:
        spawned.append((root, data_dir))

    result = apply_control(
        tmp_path, action="start", project_root=tmp_path, spawn=spawn
    )
    assert result["ok"] is True
    assert result["paused"] is False
    assert result["started"] is True
    assert spawned == [(tmp_path, tmp_path)]


def test_effective_rotate_uses_cli_until_slider_writes(tmp_path: Path) -> None:
    assert effective_rotate_s(tmp_path, 90.0) == 90.0
    assert effective_rotate_s(tmp_path, 0.0) == 0.0
    apply_control(tmp_path, action="rotate", rotate_s=15)
    assert effective_rotate_s(tmp_path, 90.0) == 15.0


def test_stop_and_spawn_source_stay_paper_only() -> None:
    source = inspect.getsource(apply_control) + inspect.getsource(default_spawn)
    assert "AsyncSecureClient" not in source
    assert "cancel_all" not in source
    assert "ALLOW_LIVE" not in source
    assert "ARB_MODE" in inspect.getsource(default_spawn)
    assert "paper_run.py" in inspect.getsource(default_spawn)
    assert "--place-orders" not in inspect.getsource(default_spawn)
    assert "--all-markets" in inspect.getsource(default_spawn)
    assert "--watch-pairs" in inspect.getsource(default_spawn)
    assert "--list-window-s" in inspect.getsource(default_spawn)
    assert '"60"' in inspect.getsource(default_spawn)


def test_start_resumes_ws_stale_when_no_halt_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "paper"
    data_dir.mkdir()
    store = StateStore(data_dir / "state.sqlite")
    store.set_halted(True, reason="ws_stale")
    spawned: list[tuple[Path, Path]] = []

    def spawn(root: Path, data_dir: Path) -> None:
        spawned.append((root, data_dir))

    result = apply_control(
        data_dir, action="start", project_root=tmp_path, spawn=spawn
    )
    assert result["ok"] is True
    assert resume_paper_halt(tmp_path, data_dir) is True
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is False
    assert restored.halt_reason == ""
    assert spawned == [(tmp_path, data_dir)]


def test_start_acks_hedge_incidents_so_evaluate_does_not_retrip(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "paper"
    data_dir.mkdir()
    store = StateStore(data_dir / "state.sqlite")
    now = 20_000
    store.record_hedge_incident(now - 300)
    store.record_hedge_incident(now - 200)
    store.record_hedge_incident(now - 100)
    store.set_halted(True, reason="hedge_incidents")
    apply_control(data_dir, action="start", project_root=tmp_path, spawn=lambda *_: None)
    assert store.restore().halted is False
    assert store.hedge_resume_ms() is not None
    ks = KillSwitch(
        project_root=tmp_path,
        state=store,
        settings=Settings(
            arb_mode="paper",
            max_notional_per_trade=d("25"),
            max_daily_loss=d("50"),
            max_open_pairs=3,
            min_edge=d("0.01"),
            max_gap=d("0.08"),
            stale_ms=400,
            hedge_timeout_ms=1500,
            ws_stale_ms=3000,
        ),
    )
    assert ks.evaluate(daily_pnl=d("10"), ws_age_ms=0, now_ms=now + 50) is True


def test_start_does_not_resume_when_halt_file_present(tmp_path: Path) -> None:
    data_dir = tmp_path / "paper"
    data_dir.mkdir()
    store = StateStore(data_dir / "state.sqlite")
    store.set_halted(True, reason="ws_stale")
    (tmp_path / "HALT").write_text("stop\n", encoding="utf-8")
    apply_control(data_dir, action="start", project_root=tmp_path, spawn=lambda *_: None)
    restored = StateStore(data_dir / "state.sqlite").restore()
    assert restored.halted is True
    assert restored.halt_reason == "ws_stale"
    assert resume_paper_halt(tmp_path, data_dir) is False


def test_write_control_does_not_touch_risk_keys(tmp_path: Path) -> None:
    write_control(tmp_path, read_control(tmp_path))
    apply_control(tmp_path, action="rotate", rotate_s=100)
    blob = (tmp_path / "control.json").read_text(encoding="utf-8")
    for banned in ("stale_ms", "min_edge", "max_gap", "private_key", "wallet", "ALLOW_LIVE"):
        assert banned not in blob
