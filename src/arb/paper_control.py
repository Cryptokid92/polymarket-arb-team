"""Local paper-runner control file. Pause/resume and watch-rotate only.

Never places or cancels live orders. Never creates ALLOW_LIVE.
Start may exec scripts/paper_run.py with ARB_MODE=paper.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arb.state import StateStore

CONTROL_FILENAME = "control.json"
PID_FILENAME = "paper_run.pid"
ROTATE_MIN_S = 1
ROTATE_MAX_S = 120
# Same default as arb.app.WATCH_ROTATE_S. Do not import app (cycle).
ROTATE_DEFAULT_S = 1

SpawnFn = Callable[[Path, Path], None]


@dataclass
class PaperControl:
    paused: bool = False
    rotate_s: int | None = None


def clamp_rotate_s(value: object) -> int:
    try:
        raw = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raw = ROTATE_DEFAULT_S
    if raw < ROTATE_MIN_S:
        return ROTATE_MIN_S
    if raw > ROTATE_MAX_S:
        return ROTATE_MAX_S
    return raw


def control_path(data_dir: Path) -> Path:
    return Path(data_dir) / CONTROL_FILENAME


def pid_path(data_dir: Path) -> Path:
    return Path(data_dir) / PID_FILENAME


def read_control(data_dir: Path) -> PaperControl:
    path = control_path(data_dir)
    if not path.is_file():
        return PaperControl()
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PaperControl()
    if not isinstance(parsed, dict):
        return PaperControl()
    paused = parsed.get("paused") is True
    rotate_raw = parsed.get("rotate_s")
    rotate_s = clamp_rotate_s(rotate_raw) if rotate_raw is not None else None
    return PaperControl(paused=paused, rotate_s=rotate_s)


def write_control(data_dir: Path, control: PaperControl) -> None:
    path = control_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"paused": bool(control.paused)}
    if control.rotate_s is not None:
        payload["rotate_s"] = clamp_rotate_s(control.rotate_s)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    tmp.replace(path)


def effective_rotate_s(data_dir: Path, fallback: float) -> float:
    """Control-file rotate overrides the runner flag. 0 from CLI still disables."""
    control = read_control(data_dir)
    if control.rotate_s is None:
        return fallback
    return float(control.rotate_s)


def write_pid(data_dir: Path, pid: int | None = None) -> None:
    path = pid_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid() if pid is None else pid), encoding="utf-8")


def clear_pid(data_dir: Path) -> None:
    path = pid_path(data_dir)
    if path.is_file():
        path.unlink()


def read_pid(data_dir: Path) -> int | None:
    path = pid_path(data_dir)
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def runner_is_alive(data_dir: Path) -> bool:
    pid = read_pid(data_dir)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def default_spawn(project_root: Path, data_dir: Path) -> None:
    """Exec paper_run only. ARB_MODE=paper. No trading client in this process."""
    script = Path(project_root) / "scripts" / "paper_run.py"
    env = os.environ.copy()
    env["ARB_MODE"] = "paper"
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    log = Path(data_dir) / "paper_run.log"
    handle = log.open("a", encoding="utf-8")
    subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--data-dir",
            str(data_dir),
            "--seconds",
            "3600",
            "--all-markets",
            "--watch-rotate-s",
            "1",
            "--list-window-s",
            "60",
        ],
        cwd=str(project_root),
        env=env,
        stdout=handle,
        stderr=handle,
        start_new_session=True,
    )


def resume_paper_halt(project_root: Path, data_dir: Path) -> bool:
    """Human Start only. Clears sqlite halt when no HALT file is present.

    Never called from the runner loop. Daily-loss / hedge stay halted until
    this human click. Start acks existing hedge rows so evaluate() does not
    immediately re-trip the same three. Three new hedges in the next hour
    still kill. A HALT file still blocks resume.
    """
    root = Path(project_root)
    folder = Path(data_dir)
    if (root / "HALT").is_file() or (folder / "HALT").is_file():
        return False
    sqlite = folder / "state.sqlite"
    if not sqlite.is_file():
        return True
    store = StateStore(sqlite)
    if not store.restore().halted:
        return True
    store.set_halted(False)
    store.set_hedge_resume_ms(time.time_ns() // 1_000_000)
    return True


def apply_control(
    data_dir: Path,
    *,
    action: str,
    rotate_s: object | None = None,
    project_root: Path | None = None,
    spawn: SpawnFn | None = None,
) -> dict[str, Any]:
    """Local start/stop/rotate. Stop pauses. Start resumes or execs paper_run."""
    control = read_control(data_dir)
    started = False
    if action == "rotate":
        if rotate_s is None:
            return {
                "ok": False,
                "error": "rotate_s required",
                "paused": control.paused,
                "rotate_s": control.rotate_s if control.rotate_s is not None else ROTATE_DEFAULT_S,
                "started": False,
                "runner_alive": runner_is_alive(data_dir),
            }
        control.rotate_s = clamp_rotate_s(rotate_s)
        write_control(data_dir, control)
    elif action == "stop":
        control.paused = True
        write_control(data_dir, control)
    elif action == "start":
        control.paused = False
        write_control(data_dir, control)
        root = Path(project_root) if project_root is not None else Path.cwd()
        resume_paper_halt(root, Path(data_dir))
        if not runner_is_alive(data_dir):
            (spawn or default_spawn)(root, Path(data_dir))
            started = True
    else:
        return {
            "ok": False,
            "error": "unknown action",
            "paused": control.paused,
            "rotate_s": control.rotate_s if control.rotate_s is not None else ROTATE_DEFAULT_S,
            "started": False,
            "runner_alive": runner_is_alive(data_dir),
        }
    shown_rotate = (
        control.rotate_s if control.rotate_s is not None else ROTATE_DEFAULT_S
    )
    return {
        "ok": True,
        "paused": control.paused,
        "rotate_s": shown_rotate,
        "started": started,
        "runner_alive": runner_is_alive(data_dir) or started,
    }
