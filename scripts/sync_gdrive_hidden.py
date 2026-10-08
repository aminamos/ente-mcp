"""Sync pictures dropped into Google Drive 'Ente Hidden' into E:\\development\\ente-queue\\.hidden.

Can be run standalone, on a loop, or as a Paseo/Windows scheduled task.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

GDRIVE_DIR = Path(r"E:\Google Drive Streaming\My Drive\Ente Hidden")
ENTE_HIDDEN = Path(r"E:\development\ente-queue\.hidden")

MEDIA_EXTS = {
    "jpg",
    "jpeg",
    "png",
    "gif",
    "webp",
    "heic",
    "heif",
    "avif",
    "bmp",
    "tiff",
    "mp4",
    "mov",
    "webm",
    "mkv",
    "m4v",
}


def sync_once() -> int:
    if not GDRIVE_DIR.exists():
        return 0
    ENTE_HIDDEN.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in GDRIVE_DIR.glob("*"):
        if item.is_file() and not item.name.startswith("."):
            ext = item.suffix.lower().lstrip(".")
            if ext in MEDIA_EXTS:
                dest = ENTE_HIDDEN / item.name
                if dest.exists() and dest.resolve() == item.resolve():
                    continue
                # If destination file already exists with different name, avoid collision
                if dest.exists():
                    stem = item.stem
                    dest = ENTE_HIDDEN / f"{stem}_{int(time.time())}.{ext}"
                try:
                    shutil.move(str(item), str(dest))
                    print(f"Moved {item.name} -> {dest}")
                    count += 1
                except Exception as e:
                    print(f"Error moving {item.name}: {e}", file=sys.stderr)
    return count


def main() -> int:
    loop = "--loop" in sys.argv or "--watch" in sys.argv
    if not loop:
        synced = sync_once()
        print(f"Synced {synced} file(s).")
        return 0

    print("Watching Google Drive 'Ente Hidden' folder for new pictures...")
    while True:
        try:
            sync_once()
        except Exception as e:
            print(f"Error in sync loop: {e}", file=sys.stderr)
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
