"""Ente museum drain driver: prune synced, quarantine stuck, top up queue.

One-shot (run every 5 min via Dev\\EnteFeedTopup task):

1. PRUNE: delete queue files already in syncedFiles (covers both uploaded
   and alreadyUploaded/dupe-skipped - the app persists both). Local disk
   only; nothing remote is ever touched.
2. QUARANTINE: files lingering in queue across many runs without syncing
   (unsupported/tooLarge - the app never persists those) move to
   staging/_unuploadable/ for review instead of blocking the feeder.
3. FEED: if pending queue < LOW_WATER and etne RAM is under cap, move the
   next BATCH from hold/ preserving album paths.

Logs to E:\\development\\ente-queue-staging\\feeder.log.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

QUEUE = Path(r"E:\development\ente-queue")
HOLD = Path(r"E:\development\ente-queue-staging\hold")
STUCK = Path(r"E:\development\ente-queue-staging\_unuploadable")
SIGHTINGS = Path(r"E:\development\ente-queue-staging\sightings.json")
WATCH_STATUS = Path(r"C:\Users\amina\AppData\Roaming\etne\watch-status.json")
LOG = Path(r"E:\development\ente-queue-staging\feeder.log")
LOW_WATER = 100
BATCH = 300
RAM_CAP_MB = 3500
STUCK_SMALL_RUNS = 6      # <200MB unsynced this many runs -> quarantine
STUCK_BIG_RUNS = 24       # >=200MB gets a longer leash (slow uplink)
BIG_BYTES = 200 * (1 << 20)
CREATE_NO_WINDOW = 0x08000000


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(line.strip())


def queue_files() -> dict[str, Path]:
    """relpath (forward slashes) -> absolute path for live queue files."""
    out: dict[str, Path] = {}
    if not QUEUE.is_dir():
        return out
    for root, _dirs, files in os.walk(QUEUE):
        for fn in files:
            if fn.startswith("."):
                continue
            p = Path(root) / fn
            out[str(p.relative_to(QUEUE)).replace("\\", "/")] = p
    return out


def synced_relpaths() -> set[str]:
    try:
        d = json.loads(WATCH_STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log(f"watch-status unreadable: {exc}")
        return set()
    out: set[str] = set()
    for m in d.get("mappings", []):
        folder = str(m.get("folderPath", "")).replace("\\", "/")
        for s in m.get("syncedFiles", []):
            p = str(s.get("path", "")).replace("\\", "/")
            if folder and p.startswith(folder):
                out.add(p[len(folder):].lstrip("/"))
    return out


def etne_ram_mb() -> int:
    import csv as _csv

    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq etne.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, timeout=20,
        ).stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return 0
    peak = 0
    try:
        rows = list(_csv.reader(out.splitlines()))
    except _csv.Error:
        return 0
    for parts in rows:
        # Image Name, PID, Session Name, Session#, Mem Usage ("1,424,308 K")
        if len(parts) >= 5 and parts[0].strip().lower() == "etne.exe":
            mem = parts[4].replace(",", "").upper().replace(" K", "").strip()
            try:
                peak = max(peak, int(mem) // 1024)
            except ValueError:
                pass
    return peak


def main() -> int:
    live = queue_files()
    synced = synced_relpaths()

    # 1. Prune synced (uploaded or dupe-skipped) local files.
    pruned = freed = 0
    for rel in sorted(set(live) & synced):
        p = live.pop(rel)
        try:
            freed += p.stat().st_size
            p.unlink()
            pruned += 1
        except OSError as exc:
            log(f"prune failed {rel}: {exc}")
    if pruned:
        log(f"pruned {pruned} synced local files ({freed / (1 << 20):.0f} MB freed)")

    # 2. Quarantine files stuck across many runs (unsupported/tooLarge).
    try:
        sightings: dict[str, int] = json.loads(SIGHTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sightings = {}
    sightings = {r: sightings.get(r, 0) + 1 for r in live}
    quarantined = 0
    for rel, runs in sorted(sightings.items()):
        p = live.get(rel)
        if p is None:
            continue
        try:
            big = p.stat().st_size >= BIG_BYTES
        except OSError:
            continue
        if runs >= (STUCK_BIG_RUNS if big else STUCK_SMALL_RUNS):
            dest = STUCK / rel
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dest))
                del live[rel]
                quarantined += 1
                log(f"quarantined stuck file ({runs} runs): {rel}")
            except OSError as exc:
                log(f"quarantine failed {rel}: {exc}")
    SIGHTINGS.write_text(json.dumps({r: c for r, c in sightings.items() if r in live}),
                         encoding="utf-8")
    if quarantined:
        log(f"quarantined {quarantined} unuploadable -> {STUCK}")

    # 3. Feed next batch if queue is low and RAM allows.
    pending = len(live)
    if pending >= LOW_WATER:
        log(f"queue pending={pending}, no feed needed")
        return 0
    ram = etne_ram_mb()
    if ram > RAM_CAP_MB:
        log(f"skip feed: etne RAM {ram}MB > cap (pending={pending})")
        return 0
    if not HOLD.is_dir():
        log("hold dir missing, nothing to feed")
        return 0
    moved = 0
    for root, _dirs, files in os.walk(HOLD):
        if moved >= BATCH:
            break
        for fn in sorted(files):
            if moved >= BATCH:
                break
            if fn.startswith("."):
                continue
            src = Path(root) / fn
            dest = QUEUE / src.relative_to(HOLD)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                moved += 1
            except OSError as exc:
                log(f"move failed {src.name}: {exc}")
                return 1
    for root, dirs, files in os.walk(HOLD, topdown=False):
        if not dirs and not files:
            try:
                os.rmdir(root)
            except OSError:
                pass
    hold_left = sum(1 for _r, _d, fs in os.walk(HOLD) for f in fs if not f.startswith("."))
    log(f"fed {moved} (pending was {pending}, hold left {hold_left}, etne {ram}MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
