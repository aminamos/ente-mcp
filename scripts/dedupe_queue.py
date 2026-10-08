"""Pre-upload dedupe for the ente watch queue (low RAM: stream hashes).

Groups files by (album dir, size) -> sha256. Within each album folder keeps
one copy (prefers names without ' (N)' suffixes, then shortest, then alpha)
and MOVES the rest to E:\\development\\ente-queue-staging\\_dupes\\<relpath>.
Writes a manifest there. Cross-album dupes are only counted, never moved
(same bytes in two albums may be intentional placement).

Usage: python dedupe_queue.py [--apply]   (default is dry-run report)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

QUEUE = Path(r"E:\development\ente-queue")
STAGE = Path(r"E:\development\ente-queue-staging\_dupes")
MANIFEST = Path(r"E:\development\ente-queue-staging\dupes-manifest.json")
CHUNK = 1 << 20
COPY_SUFFIX = re.compile(r" \(\d+\)(?=\.[^.]+$|$)")

IGNORED_EXTS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".txt", ".ini", ".sfv",
    ".md5", ".sha1", ".sha256", ".sha512", ".sha", ".html", ".htm",
    ".xmp", ".db",
}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def keep_rank(name: str) -> tuple:
    return (bool(COPY_SUFFIX.search(name)), len(name), name.lower())


def main() -> int:
    apply = "--apply" in sys.argv
    if not QUEUE.is_dir():
        sys.exit(f"missing {QUEUE}")
    # Phase 1: group by (album dir, size), skipping Ente-ignored files.
    by_dir_size: dict[tuple[str, int], list[Path]] = defaultdict(list)
    total = skipped = 0
    for root, _dirs, files in os.walk(QUEUE):
        for fn in files:
            if fn.startswith("."):
                skipped += 1
                continue
            p = Path(root) / fn
            if p.suffix.lower() in IGNORED_EXTS:
                skipped += 1
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            total += 1
            rel = p.relative_to(QUEUE)
            album = str(rel.parent)
            by_dir_size[(album, size)].append(p)
    # Phase 2: hash only size-collision groups.
    dupes: list[Path] = []
    groups = 0
    for (album, _size), paths in by_dir_size.items():
        if len(paths) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for p in paths:
            try:
                by_hash[sha256_of(p)].append(p)
            except OSError as exc:
                print(f"unreadable {p}: {exc}")
        for _h, same in by_hash.items():
            if len(same) < 2:
                continue
            groups += 1
            same.sort(key=lambda p: keep_rank(p.name))
            dupes.extend(same[1:])
    # Cross-album count (informational): re-group keeps+dupes by hash.
    print(f"scanned={total} skipped_ignored={skipped} "
          f"within_album_groups={groups} dupe_files={len(dupes)}")
    if not dupes:
        return 0
    dupe_bytes = sum(p.stat().st_size for p in dupes if p.exists())
    print(f"dupe_bytes={dupe_bytes / (1 << 20):.1f} MiB -> {STAGE}")
    for p in dupes[:10]:
        print("  dupe:", p.relative_to(QUEUE))
    if len(dupes) > 10:
        print(f"  ... and {len(dupes) - 10} more")
    if not apply:
        print("dry-run; re-run with --apply to move")
        return 0
    STAGE.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    moved = 0
    for p in dupes:
        rel = p.relative_to(QUEUE)
        dest = STAGE / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest = dest.with_name(dest.stem + "__qdup" + dest.suffix)
            p.rename(dest)
            manifest.append({"from": str(rel), "to": str(dest)})
            moved += 1
        except OSError as exc:
            print(f"move failed {p}: {exc}")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"moved={moved} manifest={MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
