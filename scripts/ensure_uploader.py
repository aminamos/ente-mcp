"""Keep etne --hidden running so watch-folder uploads never stall.

MCP only drops files into E:\\development\\ente-queue. Uploads need the
hidden uploader window. This process is independent of gallery Quit.

  pythonw ensure_uploader.py          # start once if missing
  pythonw ensure_uploader.py --watch  # loop every 15s (login Run)

Uploads and `ente export` must never run at once (machine freezes).
While E:\\development\\ente-mcp\\state\\export-active names a live pid,
this script pauses and kills etne.exe stragglers; once the pid is dead
the marker is swept and uploads resume automatically.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

EXE = Path(
    r"E:\development\ente-custom\desktop\dist\win-unpacked\etne.exe"
)
EXPORT_MARKER = Path(r"E:\development\ente-mcp\state\export-active")
CREATE_NO_WINDOW = 0x08000000
WATCH_SECONDS = 15


def uploader_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq etne.exe", "/NH"],
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )
    return "etne.exe" in (result.stdout or "")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
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


def export_active() -> bool:
    """True while export-active names a live pid; sweeps stale markers."""
    if not EXPORT_MARKER.is_file():
        return False
    try:
        data = json.loads(EXPORT_MARKER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    pids = [p for p in (data.get("parent"), data.get("child")) if isinstance(p, int)]
    if any(pid_alive(p) for p in pids):
        return True
    try:
        EXPORT_MARKER.unlink()
    except OSError:
        pass
    return False


def kill_uploader() -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/IM", "etne.exe"],
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )


def start_uploader() -> int:
    if export_active():
        if uploader_running():
            kill_uploader()  # straggler mid-export; marker keeps it dead
        return 0
    if uploader_running():
        return 0
    if not EXE.is_file():
        print(f"missing {EXE}", file=sys.stderr)
        return 1
    subprocess.Popen(
        [str(EXE), "--hidden"],
        close_fds=True,
        creationflags=CREATE_NO_WINDOW,
        env={**os.environ, "UV_THREADPOOL_SIZE": "24"},
    )
    return 0


def main() -> int:
    watch = "--watch" in sys.argv
    while True:
        code = start_uploader()
        if not watch:
            return code
        time.sleep(WATCH_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
