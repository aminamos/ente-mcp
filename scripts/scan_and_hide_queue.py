#!/usr/bin/env python3
"""Headless NSFW scanner and auto-hider for local Ente queue.

Scans all non-hidden folders in E:/development/ente-queue, evaluates images
with Falconsai/nsfw_image_detection on CUDA (RTX 4070 SUPER), and moves
any image with nsfw_score >= threshold (default 0.85) directly into .hidden.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import List, Tuple

import torch
from PIL import Image, ImageOps
from transformers import AutoImageProcessor, AutoModelForImageClassification

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}
MODEL_ID = "Falconsai/nsfw_image_detection"


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scanned_files (
            filepath TEXT PRIMARY KEY,
            filename TEXT,
            album TEXT,
            file_size INTEGER,
            nsfw_score REAL,
            moved INTEGER,
            dest_path TEXT,
            scanned_at REAL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_album ON scanned_files(album)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_moved ON scanned_files(moved)")
    conn.commit()
    return conn


def get_scanned_set(conn: sqlite3.Connection) -> set[str]:
    cur = conn.cursor()
    cur.execute("SELECT filepath FROM scanned_files")
    return {row[0] for row in cur.fetchall()}


def get_safe_dest(hidden_dir: Path, src: Path) -> Path:
    dest = hidden_dir / src.name
    if not dest.exists():
        return dest
    stem = src.stem
    ext = src.suffix
    ts = int(time.time())
    h = hashlib.sha256(str(src).encode()).hexdigest()[:6]
    return hidden_dir / f"{stem}_{ts}_{h}{ext}"


def load_image(path: Path) -> Image.Image | None:
    try:
        with Image.open(path) as opened:
            img = ImageOps.exif_transpose(opened).convert("RGB")
            # Downscale if excessively large to keep memory low
            if img.width > 1200 or img.height > 1200:
                img.thumbnail((1024, 1024), Image.Resampling.BILINEAR)
            return img.copy()
    except Exception as e:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan local Ente queue for NSFW and move to .hidden")
    parser.add_argument(
        "--queue-dir",
        default=r"E:\development\ente-queue",
        help="Root path to ente-queue folder",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="NSFW confidence score threshold (default: 0.85)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Batch size for GPU inference (default: 16)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max images to process in this run",
    )
    parser.add_argument(
        "--albums",
        nargs="*",
        default=None,
        help="Optional specific album folder names to scan",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without actually moving files",
    )
    parser.add_argument(
        "--db",
        default=r"E:\development\ente-queue\nsfw_scan_progress.sqlite",
        help="Path to progress SQLite database",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queue_dir = Path(args.queue_dir).resolve()
    hidden_dir = queue_dir / ".hidden"
    hidden_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db).resolve()

    print("=" * 65, flush=True)
    print("  Ente Queue Headless NSFW Scanner & Auto-Hider", flush=True)
    print("=" * 65, flush=True)
    print(f"Queue Root:    {queue_dir}", flush=True)
    print(f"Hidden Target: {hidden_dir}", flush=True)
    print(f"Threshold:     {args.threshold * 100:.1f}% ({args.threshold})", flush=True)
    print(f"Batch Size:    {args.batch_size}", flush=True)
    print(f"Mode:          {'DRY-RUN (no moves)' if args.dry_run else 'LIVE (automatic move)'}", flush=True)
    print(f"Progress DB:   {db_path}", flush=True)

    # CUDA & ML initialization
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Compute Device: {device}", flush=True)
    if device.type == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}", flush=True)
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

    print(f"Loading vision model '{MODEL_ID}'...", flush=True)
    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForImageClassification.from_pretrained(MODEL_ID).to(device)
    model.eval()
    print("Vision model loaded successfully.", flush=True)

    # Initialize DB & find files
    conn = init_db(db_path)
    scanned_set = get_scanned_set(conn)
    print(f"Already scanned previously in DB: {len(scanned_set)} files", flush=True)

    allowed_albums = set(args.albums) if args.albums else None

    # Discover candidate files
    candidates: List[Path] = []
    for entry in queue_dir.iterdir():
        if not entry.is_dir():
            continue
        # Never scan .hidden or hidden dotfolders
        if entry.name.startswith("."):
            continue
        if allowed_albums and entry.name not in allowed_albums:
            continue

        for root, _, files in os.walk(entry):
            for file in files:
                p = Path(root) / file
                if p.suffix.lower() in IMAGE_EXTENSIONS:
                    if str(p) not in scanned_set:
                        candidates.append(p)

    total_candidates = len(candidates)
    if args.limit:
        candidates = candidates[:args.limit]
    print(f"Pending candidate images to scan: {len(candidates)} (out of {total_candidates} unindexed)", flush=True)

    if not candidates:
        print("No pending images found to scan. All done!", flush=True)
        conn.close()
        return 0

    scanned_count = 0
    moved_count = 0
    start_time = time.time()

    # Process in batches
    for i in range(0, len(candidates), args.batch_size):
        batch_paths = candidates[i : i + args.batch_size]
        loaded_batch: List[Tuple[Path, Image.Image]] = []

        for p in batch_paths:
            img = load_image(p)
            if img is not None:
                loaded_batch.append((p, img))
            else:
                # Corrupted or unreadable image: record in DB with score 0
                conn.execute(
                    "INSERT OR REPLACE INTO scanned_files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(p), p.name, p.parent.name, p.stat().st_size if p.exists() else 0, -1.0, 0, None, time.time())
                )

        if not loaded_batch:
            conn.commit()
            continue

        valid_paths = [item[0] for item in loaded_batch]
        valid_images = [item[1] for item in loaded_batch]

        inputs = processor(images=valid_images, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.inference_mode():
            if device.type == "cuda":
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    logits = model(**inputs).logits
            else:
                logits = model(**inputs).logits

            probs = torch.softmax(logits, dim=-1).detach().cpu().tolist()

        db_rows = []
        for p, prob in zip(valid_paths, probs):
            # Falconsai id2label: {0: 'normal', 1: 'nsfw'}
            nsfw_score = float(prob[1])
            scanned_count += 1
            album_name = p.parent.name
            size = p.stat().st_size if p.exists() else 0

            if nsfw_score >= args.threshold:
                if args.dry_run:
                    print(f"  [WOULD HIDE] ({nsfw_score * 100:5.1f}%) {album_name}/{p.name}", flush=True)
                    db_rows.append((str(p), p.name, album_name, size, nsfw_score, 0, None, time.time()))
                    moved_count += 1
                else:
                    dest = get_safe_dest(hidden_dir, p)
                    try:
                        shutil.move(str(p), str(dest))
                        print(f"  [MOVED -> .hidden] ({nsfw_score * 100:5.1f}%) {album_name}/{p.name} -> {dest.name}", flush=True)
                        db_rows.append((str(p), p.name, album_name, size, nsfw_score, 1, str(dest), time.time()))
                        moved_count += 1
                    except Exception as err:
                        print(f"  [MOVE ERROR] {p.name}: {err}", flush=True)
                        db_rows.append((str(p), p.name, album_name, size, nsfw_score, 0, None, time.time()))
            else:
                db_rows.append((str(p), p.name, album_name, size, nsfw_score, 0, None, time.time()))

        conn.executemany(
            "INSERT OR REPLACE INTO scanned_files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            db_rows
        )
        conn.commit()

        # Print progress update
        elapsed = time.time() - start_time
        rate = scanned_count / max(1.0, elapsed)
        if (i // args.batch_size) % 5 == 0 or scanned_count >= len(candidates):
            print(f"Progress: {scanned_count}/{len(candidates)} photos | {moved_count} moved to .hidden | {rate:.1f} photos/sec", flush=True)

        if device.type == "cuda" and (i // args.batch_size) % 50 == 0:
            torch.cuda.empty_cache()

    elapsed = time.time() - start_time
    print("=" * 65, flush=True)
    print(f"Scan complete in {elapsed:.1f}s!", flush=True)
    print(f"Total photos evaluated:    {scanned_count}", flush=True)
    print(f"Photos moved to .hidden:   {moved_count}", flush=True)
    print(f"Average speed:             {scanned_count / max(1.0, elapsed):.1f} photos/sec", flush=True)
    print("=" * 65, flush=True)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
