from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ente_mcp.config import Client
from ente_mcp.paths import posix
from ente_mcp.process import process_label, process_running

# Kept in sync with ente/web apps/photos/src/services/watch.ts
IGNORED_EXTENSIONS = {
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "bz2",
    "txt",
    "ini",
    "sfv",
    "md5",
    "sha1",
    "sha256",
    "sha512",
    "sha",
    "html",
    "htm",
    "xmp",
    "db",
}


def load_store(client: Client) -> dict[str, Any]:
    path = client.watch_store()
    if path is None or not path.exists():
        return {"mappings": []}
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text) if text.strip() else {"mappings": []}
    if not isinstance(data.get("mappings"), list):
        data["mappings"] = []
    return data


def write_store(client: Client, store: dict[str, Any]) -> None:
    path = client.watch_store()
    if path is None:
        raise ValueError(f"client {client.name!r} has no desktop profile")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent="\t") + "\n", encoding="utf-8")


def mapping_for(store: dict[str, Any], folder: Path) -> dict[str, Any] | None:
    wanted = posix(folder).lower()
    for mapping in store["mappings"]:
        if posix(mapping.get("folderPath") or "").lower() == wanted:
            return mapping
    return None


def synced_set(mapping: dict[str, Any] | None) -> set[str]:
    if not mapping:
        return set()
    return {
        posix(item.get("path") or "").lower()
        for item in mapping.get("syncedFiles") or []
        if item.get("path")
    }


def ignored_set(mapping: dict[str, Any] | None) -> set[str]:
    if not mapping:
        return set()
    return {posix(p).lower() for p in (mapping.get("ignoredFiles") or [])}


def is_media(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    ext = path.suffix.lower().lstrip(".")
    if not ext or ext in IGNORED_EXTENSIONS:
        return False
    return True


def walk_sources(raw_paths: list[str]) -> tuple[list[Path], list[dict[str, str]]]:
    files: list[Path] = []
    skipped: list[dict[str, str]] = []
    for raw in raw_paths:
        src = Path(raw).expanduser()
        try:
            src = src.resolve(strict=True)
        except FileNotFoundError:
            skipped.append({"path": raw, "reason": "not found"})
            continue
        if src.is_file():
            if is_media(src):
                files.append(src)
            else:
                skipped.append({"path": str(src), "reason": "ignored by Ente"})
            continue
        if src.is_dir():
            for child in src.rglob("*"):
                if child.is_file() and is_media(child):
                    files.append(child)
            continue
        skipped.append({"path": str(src), "reason": "not a file or directory"})
    return files, skipped


def safe_album(album: str) -> str:
    name = (album or "Inbox").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("album must be a single folder name")
    # Ente's locked Hidden items collection is named ".hidden".
    # A folder named "Hidden" creates a *visible* album in All.
    if name.casefold() in {"hidden", "hidden items", ".hidden"}:
        return ".hidden"
    return name


def hardlink_or_copy(src: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return "exists"
    try:
        os.link(src, dest)
        return "hardlink"
    except OSError:
        dest.write_bytes(src.read_bytes())
        return "copy"


def pending_in_watch(watch_folder: Path, mapping: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not watch_folder.exists():
        return []
    synced = synced_set(mapping)
    ignored = ignored_set(mapping)
    pending: list[dict[str, Any]] = []
    for path in watch_folder.rglob("*"):
        if not path.is_file() or not is_media(path):
            continue
        key = posix(path).lower()
        if key in synced or key in ignored:
            continue
        album = path.parent.name if path.parent != watch_folder else watch_folder.name
        pending.append({"path": str(path), "album": album, "bytes": path.stat().st_size})
    return pending


def require_photos(client: Client) -> None:
    if client.app != "photos":
        raise ValueError(
            f"client {client.name!r} is app={client.app}; watch folders are Photos desktop only"
        )


def resolve_watch(client: Client, watch_folder: str = "") -> Path:
    if watch_folder:
        return Path(watch_folder).expanduser()
    if client.queue is not None:
        return client.queue
    raise ValueError("pass watch_folder or set clients.<name>.queue in config")


def watch_summary(client: Client) -> dict[str, Any]:
    require_photos(client)
    store = load_store(client)
    running = process_running(client.process)
    watches = []
    mapped: set[str] = set()
    for mapping in store["mappings"]:
        folder = Path(mapping.get("folderPath") or "")
        mapped.add(posix(folder).lower())
        pending = pending_in_watch(folder, mapping)
        watches.append(
            {
                "folderPath": mapping.get("folderPath"),
                "collectionMapping": mapping.get("collectionMapping"),
                "synced": len(mapping.get("syncedFiles") or []),
                "ignored": len(mapping.get("ignoredFiles") or []),
                "pending": len(pending),
                "exists": folder.exists(),
                "registered": True,
            }
        )
    if client.queue is not None and posix(client.queue).lower() not in mapped:
        pending = pending_in_watch(client.queue, None)
        watches.append(
            {
                "folderPath": posix(client.queue),
                "collectionMapping": "parent",
                "synced": 0,
                "ignored": 0,
                "pending": len(pending),
                "exists": client.queue.exists(),
                "registered": False,
            }
        )
    store_path = client.watch_store()
    return {
        "client": client.name,
        "app": client.app,
        "running": running,
        "process": process_label(client.process),
        "watchStore": str(store_path) if store_path else None,
        "defaultQueue": posix(client.queue) if client.queue else None,
        "watches": watches,
    }


def ensure_watch(
    client: Client,
    folder: str = "",
    collection_mapping: str = "parent",
) -> dict[str, Any]:
    require_photos(client)
    if client.watch_store() is None:
        raise ValueError(f"client {client.name!r} has no desktop profile")
    mapping_kind = collection_mapping if collection_mapping in {"parent", "root"} else "parent"
    target = resolve_watch(client, folder)
    target.mkdir(parents=True, exist_ok=True)
    if process_running(client.process):
        return {
            "ok": False,
            "reason": f"{process_label(client.process)} is running; do not edit watch-status.json",
            "folder": str(target),
            "hint": "Close the app, call this again, or add the folder in Ente → Watch folders.",
        }
    store = load_store(client)
    existing = mapping_for(store, target)
    if existing:
        return {
            "ok": True,
            "wrote": False,
            "reason": "already mapped",
            "folder": posix(target),
            "collectionMapping": existing.get("collectionMapping"),
        }
    store["mappings"].append(
        {
            "collectionMapping": mapping_kind,
            "folderPath": posix(target),
            "syncedFiles": [],
            "ignoredFiles": [],
        }
    )
    write_store(client, store)
    return {
        "ok": True,
        "wrote": True,
        "folder": posix(target),
        "collectionMapping": mapping_kind,
        "watchStore": str(client.watch_store()),
    }


def queue_files(
    client: Client,
    paths: list[str],
    album: str = "Inbox",
    watch_folder: str = "",
) -> dict[str, Any]:
    require_photos(client)
    if not paths:
        raise ValueError("paths is required")
    album_name = safe_album(album)
    store = load_store(client)
    watch = resolve_watch(client, watch_folder)
    mapping = mapping_for(store, watch)
    watch.mkdir(parents=True, exist_ok=True)
    dest_dir = watch / album_name
    dest_dir.mkdir(parents=True, exist_ok=True)

    registered = mapping is not None
    running = process_running(client.process)
    registered_now = False
    if not registered and not running and client.watch_store() is not None:
        ensured = ensure_watch(client, folder=str(watch), collection_mapping="parent")
        registered = bool(ensured.get("ok"))
        registered_now = bool(ensured.get("wrote"))
        store = load_store(client)
        mapping = mapping_for(store, watch)

    files, skipped = walk_sources(paths)
    queued: list[dict[str, str]] = []
    for src in files:
        dest = dest_dir / src.name
        if dest.resolve() == src:
            skipped.append({"path": str(src), "reason": "already in destination"})
            continue
        method = hardlink_or_copy(src, dest)
        queued.append(
            {
                "src": str(src),
                "dest": str(dest),
                "method": method,
                "album": album_name,
            }
        )

    return {
        "client": client.name,
        "running": running,
        "watchFolder": posix(watch),
        "album": album_name,
        "registered": registered,
        "registeredNow": registered_now,
        "queued": queued,
        "skipped": skipped,
        "uploadWhen": (
            "immediately if the matching Ente Photos desktop is open and watching this folder; "
            "otherwise on next launch"
        ),
        "hint": None
        if registered
        else (
            "Folder is not in watch-status.json. Close Ente and run photos ensure-watch, "
            "or add it in the app."
        ),
    }


def pending_files(client: Client, limit: int = 50) -> dict[str, Any]:
    require_photos(client)
    store = load_store(client)
    items: list[dict[str, Any]] = []
    mapped: set[str] = set()
    for mapping in store["mappings"]:
        folder = Path(mapping.get("folderPath") or "")
        mapped.add(posix(folder).lower())
        for item in pending_in_watch(folder, mapping):
            item["watchFolder"] = mapping.get("folderPath")
            item["registered"] = True
            items.append(item)
    if client.queue is not None and posix(client.queue).lower() not in mapped:
        for item in pending_in_watch(client.queue, None):
            item["watchFolder"] = posix(client.queue)
            item["registered"] = False
            items.append(item)
    items.sort(key=lambda row: row["path"])
    cap = max(0, min(limit, 200))
    return {
        "client": client.name,
        "running": process_running(client.process),
        "pending": len(items),
        "items": items[:cap],
    }
