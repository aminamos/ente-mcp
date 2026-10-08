"""Build browser-sized upload batches from the ente queue (hardlinks, low RAM).

Reads E:\\development\\ente-queue, groups by album (relative parent dir),
splits into batches of <=400 files AND <=2GB, and hardlinks each batch to
E:\\development\\ente-upload-batches\\<NN>-<album>[-pN]\\.

Excluded (moved to staging, reversible, in manifest):
- Ente-ignored extensions (zip, txt, ...) - the 9GB archive.zip etc.
- .m4s DASH segments (downloader debris, not playable media).

Writes batches.json manifest + BATCHES.md checklist. Idempotent: re-runs
clear and rebuild the batches dir (hardlinks only, source untouched).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path

QUEUE = Path(r"E:\development\ente-queue")
OUT = Path(r"E:\development\ente-upload-batches")
EXCLUDED = Path(r"E:\development\ente-queue-staging\_excluded")
MANIFEST = OUT / "batches.json"
CHECKLIST = OUT / "BATCHES.md"
MAX_FILES = 400
MAX_BYTES = 2 * (1 << 30)

IGNORED_EXTS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".txt", ".ini", ".sfv",
    ".md5", ".sha1", ".sha256", ".sha512", ".sha", ".html", ".htm",
    ".xmp", ".db",
}
JUNK_EXTS = {".m4s"}


def safe(name: str) -> str:
    keep = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in name)
    return keep.strip().rstrip(".") or "album"


def main() -> int:
    if not QUEUE.is_dir():
        sys.exit(f"missing {QUEUE}")
    by_album: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    excluded: list[dict[str, str]] = []
    total = 0
    for root, _dirs, files in os.walk(QUEUE):
        for fn in sorted(files):
            if fn.startswith("."):
                continue
            p = Path(root) / fn
            ext = p.suffix.lower()
            rel = p.relative_to(QUEUE)
            if ext in IGNORED_EXTS or ext in JUNK_EXTS:
                excluded.append({"path": str(rel), "reason": f"ext {ext}"})
                continue
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            total += 1
            by_album[str(rel.parent)].append((p, sz))
    # Move excludeds to staging (reversible).
    EXCLUDED.mkdir(parents=True, exist_ok=True)
    for e in excluded:
        src = QUEUE / e["path"]
        dest = EXCLUDED / e["path"]
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest = dest.with_name(dest.stem + "__qdup" + dest.suffix)
            src.rename(dest)
            e["moved_to"] = str(dest)
        except OSError as exc:
            e["error"] = str(exc)
    # Build batches.
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    batches: list[dict] = []
    idx = 0
    for album in sorted(by_album):
        items = by_album[album]
        part = 0
        cur: list[tuple[Path, int]] = []
        cur_bytes = 0

        def flush() -> None:
            nonlocal idx, part, cur, cur_bytes
            if not cur:
                return
            part += 1
            idx += 1
            label = safe(album.replace("\\", "-"))
            name = f"{idx:02d}-{label}" + (f"-p{part}" if len(items) > MAX_FILES or sum(s for _, s in items) > MAX_BYTES else "")
            dest = OUT / name
            dest.mkdir(parents=True)
            n = 0
            for src, _sz in cur:
                try:
                    os.link(src, dest / src.name)
                    n += 1
                except OSError as exc:
                    print(f"link failed {src.name}: {exc}")
            batches.append({"batch": name, "album": album,
                            "target": ".hidden (Locked Hidden)" if album == ".hidden" or album.startswith(".hidden")
                            else album.replace("\\", " / "),
                            "files": n, "bytes": cur_bytes})
            cur, cur_bytes = [], 0

        for src, sz in items:
            if cur and (len(cur) >= MAX_FILES or cur_bytes + sz > MAX_BYTES):
                flush()
            cur.append((src, sz))
            cur_bytes += sz
        flush()
    total_b = sum(b["bytes"] for b in batches)
    total_f = sum(b["files"] for b in batches)
    MANIFEST.write_text(json.dumps(
        {"batches": batches, "excluded": excluded,
         "totals": {"files": total_f, "bytes": total_b}}, indent=1),
        encoding="utf-8")
    lines = ["# Upload batches -> photos.robusteland.box.ca",
             "",
             f"{len(batches)} batches, {total_f} files, {total_b / (1 << 30):.1f} GB.",
             "Drop ONE batch folder at a time into the web UI target album and",
             "wait for it to finish before the next (keeps browser RAM bounded).",
             "Re-dropping a batch is safe: Ente skips files already on the server.",
             "",
             "| done | batch | target album | files | size |",
             "|---|---|---|---|---|"]
    for b in batches:
        lines.append(f"| [ ] | `{b['batch']}` | {b['target']} | {b['files']} | "
                     f"{b['bytes'] / (1 << 20):.0f} MB |")
    lines += ["",
              "Targets named `.hidden...` go to the Locked Hidden section;",
              "everything else to a matching album name (create it first).",
              "",
              f"Excluded {len(excluded)} non-uploadable files -> "
              "`ente-queue-staging/_excluded/` (see batches.json)."]
    CHECKLIST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"batches={len(batches)} files={total_f} GB={total_b / (1 << 30):.1f} "
          f"excluded={len(excluded)}")
    print(f"manifest={MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
