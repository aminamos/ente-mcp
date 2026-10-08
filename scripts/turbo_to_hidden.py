"""Download a turbo.cr /d/ file into Ente locked Hidden (.hidden).

Skips the download-page Altcha by using /api/sign (same as gallery-dl).

  python turbo_to_hidden.py https://turbo.cr/d/r5g2-i2soq4q3
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

DOWNLOADS = Path(r"D:\Downloads")
ENTE_QUEUE = Path(r"E:\development\ente-mcp\.venv\Scripts\ente-mcp.exe")
FILE_ID = re.compile(r"/d/([A-Za-z0-9_-]+)")
UA = "Mozilla/5.0"


def file_id(url: str) -> str:
    m = FILE_ID.search(url)
    if not m:
        raise SystemExit(f"not a turbo.cr /d/ URL: {url}")
    return m.group(1)


def sign(fid: str) -> dict:
    req = urllib.request.Request(
        f"https://turbo.cr/api/sign?v={fid}",
        headers={"Referer": f"https://turbo.cr/d/{fid}", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    if not data.get("success") or not data.get("url"):
        raise SystemExit(f"sign failed: {data}")
    return data


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: turbo_to_hidden.py https://turbo.cr/d/ID", file=sys.stderr)
        return 2
    fid = file_id(sys.argv[1])
    data = sign(fid)
    name = data.get("original_filename") or f"{fid}.mp4"
    dest = DOWNLOADS / name
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            "curl.exe",
            "-L",
            "--fail",
            "--retry",
            "3",
            "-A",
            UA,
            "-H",
            f"Referer: https://turbo.cr/d/{fid}",
            "-o",
            str(dest),
            data["url"],
        ]
    )
    if ENTE_QUEUE.is_file():
        subprocess.check_call(
            [str(ENTE_QUEUE), "photos", "queue", str(dest), "--album", ".hidden"]
        )
    else:
        print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
