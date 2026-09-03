from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENTE_CLI_RELEASES = "https://github.com/ente-io/ente/releases?q=tag%3Acli-v0"
# Historical/current org slugs both exist in docs; prefer ente-io then ente.
ENTE_CLI_RELEASES_ALT = "https://github.com/ente/ente/releases?q=tag%3Acli-v0"


@dataclass(frozen=True)
class EnteAccount:
    email: str
    user_id: str
    app: str
    export_dir: str


def find_ente_cli(configured: str = "ente") -> str | None:
    env = os.environ.get("ENTE_CLI")
    candidate = env or configured
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path)
        found = shutil.which(candidate)
        if found:
            return found
    return shutil.which("ente")


def run_ente(
    configured: str,
    args: list[str],
    *,
    timeout: int = 120,
    input_text: str | None = None,
) -> dict[str, Any]:
    binary = find_ente_cli(configured)
    if binary is None:
        return {
            "ok": False,
            "error": "official ente CLI not found on PATH",
            "hint": f"Install from {ENTE_CLI_RELEASES} or set ENTE_CLI / ente_cli in config.",
            "releases": ENTE_CLI_RELEASES_ALT,
        }
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"ente {' '.join(args)} timed out after {timeout}s",
            "binary": binary,
        }
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return {
        "ok": result.returncode == 0,
        "code": result.returncode,
        "binary": binary,
        "args": args,
        "stdout": stdout.strip(),
        "stderr": stderr.strip(),
    }


def parse_accounts(text: str) -> list[EnteAccount]:
    accounts: list[EnteAccount] = []
    current: dict[str, str] = {}

    def flush() -> None:
        nonlocal current
        if current.get("email") or current.get("app"):
            accounts.append(
                EnteAccount(
                    email=current.get("email", ""),
                    user_id=current.get("id", ""),
                    app=current.get("app", "").lower(),
                    export_dir=current.get("exportdir", ""),
                )
            )
        current = {}

    for line in text.splitlines():
        stripped = line.strip()
        if stripped and set(stripped) == {"="}:
            flush()
            continue
        match = re.match(r"(Email|ID|App|ExportDir)\s*:\s*(.*)$", stripped)
        if match:
            current[match.group(1).lower()] = match.group(2).strip()
    flush()
    return accounts


def list_accounts(configured: str) -> dict[str, Any]:
    result = run_ente(configured, ["account", "list"])
    if not result.get("ok"):
        return result
    accounts = [a.__dict__ for a in parse_accounts(result.get("stdout") or "")]
    return {
        "ok": True,
        "binary": result.get("binary"),
        "accounts": accounts,
        "raw": result.get("stdout"),
    }


def export_data(
    configured: str,
    *,
    shared: bool = True,
    hidden: bool = True,
    albums: list[str] | None = None,
    emails: list[str] | None = None,
    exclude_albums: list[str] | None = None,
    timeout: int = 0,
) -> dict[str, Any]:
    args = ["export"]
    if not shared:
        args.append("--shared=false")
    if not hidden:
        args.append("--hidden=false")
    if albums:
        args.extend(["--albums", ",".join(albums)])
    if emails:
        args.extend(["--emails", ",".join(emails)])
    if exclude_albums:
        args.extend(["--exclude-albums", ",".join(exclude_albums)])
    wait = timeout if timeout > 0 else 3600
    result = run_ente(configured, args, timeout=wait)
    result["note"] = (
        "Official CLI exports Photos albums and Auth codes (ente_auth.txt). "
        "Locker export is not supported by ente CLI."
    )
    return result


def auth_decrypt(
    configured: str,
    input_path: str,
    output_path: str,
    password: str = "",
) -> dict[str, Any]:
    src = Path(input_path).expanduser()
    dest = Path(output_path).expanduser()
    if not src.is_file():
        return {"ok": False, "error": f"input not found: {src}"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["auth", "decrypt", str(src), str(dest)]
    if password:
        args.extend(["--password", password])
    result = run_ente(configured, args)
    if result.get("ok"):
        result["output"] = str(dest)
        result["note"] = "Decrypted Auth export written to disk. This tool does not print TOTP secrets."
    return result


def apps_status(configured: str) -> dict[str, Any]:
    binary = find_ente_cli(configured)
    listed = list_accounts(configured) if binary else None
    accounts = (listed or {}).get("accounts") or []
    by_app: dict[str, list[dict[str, Any]]] = {"photos": [], "auth": [], "locker": []}
    for acc in accounts:
        app = (acc.get("app") or "").lower()
        if app in by_app:
            by_app[app].append(acc)
    return {
        "officialCli": binary,
        "accounts": accounts,
        "apps": {
            "photos": {
                "desktopWatchFolders": True,
                "officialExport": True,
                "accounts": by_app["photos"],
            },
            "auth": {
                "desktopWatchFolders": False,
                "officialExport": True,
                "decryptExport": True,
                "accounts": by_app["auth"],
                "note": "ente export writes ente_auth.txt for Auth accounts. Use auth decrypt for encrypted exports.",
            },
            "locker": {
                "desktopWatchFolders": False,
                "officialExport": False,
                "accounts": by_app["locker"],
                "note": (
                    "Official ente CLI accepts --app locker for account add / get-token. "
                    "Locker item export is not implemented in ente CLI."
                ),
            },
        },
        "error": None if binary else (listed or {}).get("error")
        if listed
        else "official ente CLI not found on PATH",
        "hint": None
        if binary
        else f"Install from {ENTE_CLI_RELEASES} or set ENTE_CLI.",
    }
