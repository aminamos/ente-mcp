"""Mutual exclusion between the desktop uploader and `ente export`.

Running `ente export` (official CLI) while the etne desktop uploader is
active starves the box and can freeze it. Contract:

- Export holds a byte lock on ``state/export.lock`` and writes
  ``state/export-active`` (JSON with parent + child pids).
- ``scripts/ensure_uploader.py`` checks the marker; while any pid in it
  is alive it skips relaunching etne.exe and kills stragglers.
- When the export process exits, the marker is removed (or swept as
  stale by the next ensure_uploader tick once its pids are dead) and the
  keep-alive brings etne.exe back up on its own.

Only one export may hold the lock at a time; a second caller raises
``ExportBusy`` instead of stacking two `ente export` runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ente_mcp.paths import package_dir

if sys.platform == "win32":
    import msvcrt

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
DESKTOP_EXES = ("etne.exe", "ente.exe")


class ExportBusy(RuntimeError):
    """Another `ente export` already holds the lock."""


def state_dir() -> Path:
    return package_dir() / "state"


def marker_path() -> Path:
    return state_dir() / "export-active"


def lock_path() -> Path:
    return state_dir() / "export.lock"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        for line in (result.stdout or "").splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) > 1 and parts[1] == str(pid):
                return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_marker() -> dict[str, Any]:
    try:
        data = json.loads(marker_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_marker(parent_pid: int, child_pid: int) -> None:
    marker_path().parent.mkdir(parents=True, exist_ok=True)
    marker_path().write_text(
        json.dumps({"parent": parent_pid, "child": child_pid, "started": int(time.time())}),
        encoding="utf-8",
    )


def export_active() -> bool:
    """True while a marker exists with a live pid; sweeps stale markers."""
    marker = marker_path()
    if not marker.is_file():
        return False
    data = read_marker()
    pids = [p for p in (data.get("parent"), data.get("child")) if isinstance(p, int)]
    if any(pid_alive(p) for p in pids):
        return True
    try:
        marker.unlink()
    except OSError:
        pass
    return False


def running_desktops() -> list[str]:
    found: list[str] = []
    for exe in DESKTOP_EXES:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if exe in (result.stdout or ""):
            found.append(exe)
    return found


def stop_desktops() -> list[str]:
    """Force-kill desktop ente/etne uploaders; returns names that were stopped."""
    killed: list[str] = []
    for exe in running_desktops():
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/IM", exe],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            killed.append(exe)
    return killed


def kill_tree(pid: int) -> None:
    if pid <= 0:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


class _FileLock:
    """Non-blocking single-byte lock; msvcrt on win32, fcntl elsewhere."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._path, "a+b")
        try:
            if sys.platform == "win32":
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise ExportBusy("another `ente export` is already running") from exc
        self._fh = fh

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


@contextmanager
def export_session() -> Iterator[dict[str, Any]]:
    """Hold the export mutex for one `ente export` run.

    Yields a mutable info dict; the caller sets ``info["child"]`` to the
    CLI subprocess pid once spawned so ensure_uploader can tell which
    process the marker refers to.
    """
    lock = _FileLock(lock_path())
    lock.acquire()
    info: dict[str, Any] = {"parent": os.getpid(), "child": None, "killed_desktops": []}
    try:
        write_marker(info["parent"], 0)
        info["killed_desktops"] = stop_desktops()
        yield info
    finally:
        try:
            marker_path().unlink(missing_ok=True)
        except OSError:
            pass
        lock.release()
