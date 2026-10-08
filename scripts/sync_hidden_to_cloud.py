#!/usr/bin/env python3
"""Sync locally hidden NSFW photos to official Ente Cloud .hidden collection.

Reads the moved photos from E:/development/ente-queue/nsfw_scan_progress.sqlite,
finds their corresponding file objects in the matching cloud albums on api.ente.io,
re-encrypts their file keys for the cloud .hidden collection, and calls
POST /collections/move-files to lock them in the cloud immediately.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple

import nacl.bindings
import nacl.secret
import requests

DEFAULT_DB = Path(r"E:\development\ente-queue\nsfw_scan_progress.sqlite")
DEFAULT_WORDLIST = Path(__file__).with_name("bip39-english.txt")
HIDDEN_COLLECTION_ID = 1580559965615543
AUTH_TOKEN = "qWwqpYgby6t74pZajGGt7jAIqePJnwL6TLInVOeOqGM="
API_BASE = "https://api.ente.io"

b64d = lambda s: base64.b64decode(s)
b64e = lambda b: base64.b64encode(b).decode()


def load_recovery_key(phrase: str, wordlist_path: Path) -> bytes:
    wordlist = wordlist_path.read_text(encoding="utf-8").split()
    index = {w: i for i, w in enumerate(wordlist)}
    words = phrase.split()
    bits = 0
    for w in words:
        bits = (bits << 11) | index[w]
    return (bits >> 8).to_bytes(32, "big")


def encrypt_box(data: bytes, key: bytes) -> dict:
    nonce = nacl.bindings.randombytes(24)
    return {
        "encryptedData": b64e(nacl.secret.SecretBox(key).encrypt(data, nonce).ciphertext),
        "nonce": b64e(nonce),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Move local NSFW matches to Ente cloud .hidden")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to scan progress sqlite")
    parser.add_argument("--dry-run", action="store_true", help="Find matches without calling move-files")
    parser.add_argument("--limit", type=int, default=None, help="Max cloud files to move")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 65, flush=True)
    print("  Sync Locally Flagged NSFW Photos to Ente Cloud (.hidden)", flush=True)
    print("=" * 65, flush=True)

    con = sqlite3.connect(args.db)
    cur = con.cursor()
    cur.execute("SELECT filename, album, nsfw_score FROM scanned_files WHERE moved = 1")
    target_files = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    con.close()
    print(f"Total locally moved files in SQLite: {len(target_files)}", flush=True)

    if not target_files:
        print("No moved files found in database.", flush=True)
        return 0

    phrase = "act mind clinic merry setup shuffle glory owner clever meadow valley recipe spatial satoshi coach long depart raise hawk family snow brass barrel runway"
    recovery_key = load_recovery_key(phrase, DEFAULT_WORDLIST)

    headers = {"X-Auth-Token": AUTH_TOKEN, "X-Client-Package": "io.ente.photos.desktop"}
    r = requests.get(f"{API_BASE}/users/session-validity/v2", headers=headers, timeout=30)
    ka = r.json()["keyAttributes"]
    master_key = nacl.secret.SecretBox(recovery_key).decrypt(
        b64d(ka["masterKeyEncryptedWithRecoveryKey"]),
        b64d(ka["masterKeyDecryptionNonce"]),
    )
    print("Successfully authenticated and unlocked master key.", flush=True)

    # Fetch and decrypt all albums
    r = requests.get(f"{API_BASE}/collections/v2", headers=headers, params={"sinceTime": 0}, timeout=30)
    cols = r.json().get("collections", [])
    album_map: Dict[str, Tuple[int, bytes]] = {}
    hidden_key: bytes | None = None

    for c in cols:
        if c.get("isDeleted"):
            continue
        try:
            ckey = nacl.secret.SecretBox(master_key).decrypt(b64d(c["encryptedKey"]), b64d(c["keyDecryptionNonce"]))
            name = nacl.secret.SecretBox(ckey).decrypt(b64d(c["encryptedName"]), b64d(c["nameDecryptionNonce"])).decode("utf-8")
            album_map[name] = (c["id"], ckey)
            if c["id"] == HIDDEN_COLLECTION_ID:
                hidden_key = ckey
        except Exception:
            pass

    if hidden_key is None:
        raise SystemExit(f"Could not resolve .hidden collection key (id: {HIDDEN_COLLECTION_ID})")

    print(f"Resolved {len(album_map)} cloud collections. Cloud .hidden key unlocked.", flush=True)

    albums_needed: Dict[str, Set[str]] = {}
    for filename, (album, score) in target_files.items():
        albums_needed.setdefault(album, set()).add(filename)

    total_moved = 0

    for album_name, filenames in albums_needed.items():
        if album_name not in album_map:
            print(f"  [ALBUM NOT IN CLOUD] {album_name} - skipping", flush=True)
            continue

        cid, ckey = album_map[album_name]
        print(f"\nChecking album '{album_name}' (ID: {cid}, looking for {len(filenames)} files)...", flush=True)

        since = 0
        matching_items = []

        while True:
            r = requests.get(
                f"{API_BASE}/collections/v2/diff",
                headers=headers,
                params={"collectionID": cid, "sinceTime": since},
                timeout=60,
            )
            data = r.json()
            diff = [f for f in data.get("diff", []) if not f.get("isDeleted")]
            if not diff:
                break

            for f in diff:
                since = max(since, f.get("updationTime", since))
                fk = nacl.secret.SecretBox(ckey).decrypt(b64d(f["encryptedKey"]), b64d(f["keyDecryptionNonce"]))
                meta = f.get("metadata", {})
                if not meta.get("encryptedData") or not meta.get("decryptionHeader"):
                    continue

                try:
                    st = nacl.bindings.crypto_secretstream_xchacha20poly1305_state()
                    nacl.bindings.crypto_secretstream_xchacha20poly1305_init_pull(st, b64d(meta["decryptionHeader"]), fk)
                    dec, tag = nacl.bindings.crypto_secretstream_xchacha20poly1305_pull(st, b64d(meta["encryptedData"]), None)
                    d = json.loads(dec.decode("utf-8"))
                    title = d.get("title")

                    if title in filenames:
                        # Re-encrypt file key with .hidden collection key
                        enc = encrypt_box(fk, hidden_key)
                        matching_items.append({
                            "id": f["id"],
                            "title": title,
                            "encryptedKey": enc["encryptedData"],
                            "keyDecryptionNonce": enc["nonce"],
                        })
                except Exception:
                    pass

            if not data.get("hasMore"):
                break

        print(f"  Found {len(matching_items)} matching files in cloud album '{album_name}'", flush=True)

        if not matching_items:
            continue

        if args.dry_run:
            for item in matching_items:
                print(f"  [DRY RUN] Would move file {item['id']} ({item['title']}) to .hidden", flush=True)
            total_moved += len(matching_items)
            continue

        # Execute move in batches of 100
        batch_size = 100
        for i in range(0, len(matching_items), batch_size):
            batch = matching_items[i : i + batch_size]
            payload = {
                "fromCollectionID": cid,
                "toCollectionID": HIDDEN_COLLECTION_ID,
                "files": [
                    {
                        "id": it["id"],
                        "encryptedKey": it["encryptedKey"],
                        "keyDecryptionNonce": it["keyDecryptionNonce"],
                    }
                    for it in batch
                ],
            }

            res = requests.post(f"{API_BASE}/collections/move-files", headers=headers, json=payload, timeout=60)
            if res.status_code == 200:
                for it in batch:
                    print(f"  [CLOUD MOVED -> .hidden] {album_name}/{it['title']} (File ID: {it['id']})", flush=True)
                    total_moved += 1
            else:
                print(f"  [ERROR MOVING BATCH] HTTP {res.status_code}: {res.text[:200]}", flush=True)

            if args.limit and total_moved >= args.limit:
                break

        if args.limit and total_moved >= args.limit:
            break

    print("=" * 65, flush=True)
    print(f"Finished! Total cloud files moved into .hidden: {total_moved}", flush=True)
    print("=" * 65, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
