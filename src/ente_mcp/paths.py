from __future__ import annotations

import os
import sys
from pathlib import Path


def posix(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def user_config_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / "ente-mcp"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "ente-mcp"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ente-mcp"
    return Path.home() / ".config" / "ente-mcp"


def electron_user_data(profile: str) -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / profile
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / profile
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / profile
    return Path.home() / ".config" / profile


def package_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent
