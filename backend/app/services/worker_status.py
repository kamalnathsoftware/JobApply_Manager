"""Is the worker process alive? The worker touches a heartbeat file in STORAGE_DIR every few
seconds; the API reads its age. Also lets the UI start the worker on the user's own machine."""

import os
import subprocess
import sys
import time
from pathlib import Path

from app.core.config import get_settings

ALIVE_WITHIN_S = 20.0


def _dir() -> Path:
    d = Path(get_settings().storage_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def heartbeat_path() -> Path:
    return _dir() / "worker.heartbeat"


def touch_heartbeat() -> None:
    try:
        heartbeat_path().write_text(f"{os.getpid()} {time.time()}")
    except OSError:
        pass  # never let a status file break the worker


def heartbeat_age() -> float | None:
    try:
        return max(0.0, time.time() - heartbeat_path().stat().st_mtime)
    except OSError:
        return None


def worker_alive() -> bool:
    age = heartbeat_age()
    return age is not None and age <= ALIVE_WITHIN_S


def spawn_worker() -> subprocess.Popen:
    """Start `python -m app.workers.main` detached; output goes to STORAGE_DIR/logs/worker.log."""
    log_dir = _dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out = open(log_dir / "worker.log", "ab")  # noqa: SIM115
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(
        [sys.executable, "-m", "app.workers.main"],
        stdout=out,
        stderr=subprocess.STDOUT,
        **kwargs,
    )
