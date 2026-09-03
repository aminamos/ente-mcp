from __future__ import annotations

import subprocess
import sys


def process_running(image: str | None) -> bool:
    if not image:
        return False
    name = image.strip()
    if not name:
        return False
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        exe = name if name.lower().endswith(".exe") else f"{name}.exe"
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=flags,
        )
        return exe.lower() in (result.stdout or "").lower()
    result = subprocess.run(
        ["pgrep", "-x", name],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if not name.lower().endswith(".exe"):
        extra = subprocess.run(
            ["pgrep", "-x", f"{name}.exe"],
            capture_output=True,
            text=True,
        )
        return extra.returncode == 0
    return False


def process_label(image: str | None) -> str | None:
    if not image:
        return None
    if sys.platform == "win32" and not image.lower().endswith(".exe"):
        return f"{image}.exe"
    return image
