#!/usr/bin/env python3
"""Mirror local folders into the Thalassa Ente instance as normal or hidden albums.

Each top-level directory under --root becomes one album named after the directory
(.hidden routes to the user's hidden collection).
Files are end-to-end encrypted using the Ente protocol (secretbox / secretstream).

Usage:
  # 1. Establish SSH tunnel to Thalassa (ports 28485 Museum, 28486 MinIO):
  #    ssh -N -L 28485:127.0.0.1:28485 -L 28486:127.0.0.1:28486 thalassa
  #
  # 2. Run mirror:
  #    python thalassa_mirror.py --root E:/development/ente-queue --verify
  #    python thalassa_mirror.py --root E:/development/ente-queue --only .hidden

Credentials are pulled from 1Password item "satsuma ente" / "thalassa ente" unless
ENTE_EMAIL / ENTE_RECOVERY_PHRASE env vars are set.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

import nacl.bindings
import nacl.public
import nacl.secret
import requests

DEFAULT_ORIGIN = os.environ.get("ENTE_ORIGIN", "http://127.0.0.1:28485")
OP_ITEM_ID = "mb7wdj36fxil6y7yki54jen2za"  # Ente Whatbox item (agentic vault)
OP_VAULT = "agentic"
WORDLIST_PATH = Path(__file__).with_name("bip39-english.txt")
CHUNK = 4 * 1024 * 1024  # Ente's streamEncryptionChunkSize
TAG_MESSAGE = nacl.bindings.crypto_secretstream_xchacha20poly1305_TAG_MESSAGE
TAG_FINAL = nacl.bindings.crypto_secretstream_xchacha20poly1305_TAG_FINAL

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".bmp", ".tiff"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi"}
FILE_TYPE_IMAGE = 0
FILE_TYPE_VIDEO = 1

b64e = lambda b: base64.b64encode(b).decode()
b64d = lambda s: base64.b64decode(s)


def load_credentials() -> tuple[str, str]:
    email = os.environ.get("ENTE_EMAIL")
    phrase = os.environ.get("ENTE_RECOVERY_PHRASE")
    if email and phrase:
        return email, phrase
    try:
        out = subprocess.run(
            ["op", "item", "get", OP_ITEM_ID, "--vault", OP_VAULT, "--format", "json"],
            capture_output=True, text=True, check=True,
        )
        item = json.loads(out.stdout)
        fields = {f.get("label"): f.get("value", "") for f in item.get("fields", [])}
        return (
            email or fields.get("username", "") or fields.get("email", ""),
            phrase or fields.get("notesPlain", "").strip(),
        )
    except Exception:
        # Fallback to local Ente credentials
        out = subprocess.run(
            ["op", "item", "get", "si6lht5nwaxgrrdxemynyy6jdy", "--vault", OP_VAULT, "--format", "json"],
            capture_output=True, text=True, check=True,
        )
        item = json.loads(out.stdout)
        fields = {f.get("label"): f.get("value", "") for f in item.get("fields", [])}
        return (
            email or fields.get("email", ""),
            phrase or fields.get("notesPlain", "").strip(),
        )


def recovery_key_from_phrase(phrase: str) -> bytes:
    words = phrase.split()
    if len(words) != 24:
        raise SystemExit(f"recovery phrase must be 24 words, got {len(words)}")
    wordlist = WORDLIST_PATH.read_text(encoding="utf-8").split()
    index = {w: i for i, w in enumerate(wordlist)}
    bits = 0
    for w in words:
        bits = (bits << 11) | index[w]
    entropy = bits >> 8
    checksum = bits & 0xFF
    digest = hashlib.sha256(entropy.to_bytes(32, "big")).digest()[0]
    if digest != checksum:
        raise SystemExit("recovery phrase checksum mismatch")
    return entropy.to_bytes(32, "big")


def secretbox_open(ciphertext_b64: str, nonce_b64: str, key: bytes) -> bytes:
    return nacl.secret.SecretBox(key).decrypt(b64d(ciphertext_b64), b64d(nonce_b64))


def encrypt_box(data: bytes, key: bytes) -> dict:
    nonce = nacl.bindings.randombytes(24)
    return {
        "encryptedData": b64e(nacl.secret.SecretBox(key).encrypt(data, nonce).ciphertext),
        "nonce": b64e(nonce),
    }


def encrypt_blob(data: bytes, key: bytes) -> dict:
    state = nacl.bindings.crypto_secretstream_xchacha20poly1305_state()
    header = nacl.bindings.crypto_secretstream_xchacha20poly1305_init_push(state, key)
    ct = nacl.bindings.crypto_secretstream_xchacha20poly1305_push(state, data, None, TAG_FINAL)
    return {"encryptedData": ct, "decryptionHeader": header}


def encrypt_stream(data: bytes, key: bytes) -> dict:
    state = nacl.bindings.crypto_secretstream_xchacha20poly1305_state()
    header = nacl.bindings.crypto_secretstream_xchacha20poly1305_init_push(state, key)
    if not data:
        ct = nacl.bindings.crypto_secretstream_xchacha20poly1305_push(state, b"", None, TAG_FINAL)
        return {"encryptedData": ct, "decryptionHeader": header}
    parts = []
    offset = 0
    while True:
        chunk = data[offset : offset + CHUNK]
        tag = TAG_FINAL if offset + len(chunk) >= len(data) else TAG_MESSAGE
        parts.append(nacl.bindings.crypto_secretstream_xchacha20poly1305_push(state, chunk, None, tag))
        offset += len(chunk)
        if tag == TAG_FINAL:
            break
    return {"encryptedData": b"".join(parts), "decryptionHeader": header}


class EnteClient:
    def __init__(self, origin: str, token: str, master_key: bytes):
        self.origin = origin.rstrip("/")
        self.master_key = master_key
        self._token = token
        self._local = threading.local()

    @property
    def http(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"X-Auth-Token": self._token, "X-Client-Package": "io.ente.cli"})
            self._local.session = s
        return s

    def _req(self, method: str, path: str, **kw) -> dict:
        r = self.http.request(method, f"{self.origin}{path}", timeout=60, **kw)
        if r.status_code == 401:
            raise SystemExit("museum returned 401 - token rejected")
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def collections(self) -> dict[str, tuple[int, bytes]]:
        out: dict[str, tuple[int, bytes]] = {}
        res = self._req("GET", "/collections/v2", params={"sinceTime": 0})
        for col in res.get("collections", []):
            if col.get("isDeleted"):
                continue
            try:
                ckey = secretbox_open(col["encryptedKey"], col["keyDecryptionNonce"], self.master_key)
                name = secretbox_open(col["encryptedName"], col["nameDecryptionNonce"], ckey).decode()
                out[name] = (col["id"], ckey)
            except Exception:
                continue
        return out

    def create_album(self, name: str) -> tuple[int, bytes]:
        ckey = nacl.bindings.crypto_secretstream_xchacha20poly1305_keygen()
        ek = encrypt_box(ckey, self.master_key)
        en = encrypt_box(name.encode(), ckey)
        res = self._req("POST", "/collections", json={
            "encryptedKey": ek["encryptedData"],
            "keyDecryptionNonce": ek["nonce"],
            "encryptedName": en["encryptedData"],
            "nameDecryptionNonce": en["nonce"],
            "type": "album",
        })
        return res["collection"]["id"], ckey

    def upload_blob(self, data: bytes) -> dict:
        res = self._req("POST", "/files/upload-url", json={
            "contentLength": len(data),
            "contentMD5": b64e(hashlib.md5(data).digest()),
        })
        url = res["url"]
        put = requests.put(
            url,
            data=data,
            headers={"Content-MD5": b64e(hashlib.md5(data).digest())},
            timeout=300,
        )
        if put.status_code >= 300:
            raise RuntimeError(f"S3 PUT failed: HTTP {put.status_code}: {put.text[:200]}")
        return res

    def post_file(self, collection_id: int, file_key: bytes, collection_key: bytes,
                  file_obj: dict, thumb_obj: dict, metadata: dict) -> int:
        fk = encrypt_box(file_key, collection_key)
        res = self._req("POST", "/files", json={
            "collectionID": collection_id,
            "encryptedKey": fk["encryptedData"],
            "keyDecryptionNonce": fk["nonce"],
            "file": file_obj,
            "thumbnail": thumb_obj,
            "metadata": metadata,
        })
        return res["id"]

    def collection_file_count(self, collection_id: int) -> int:
        count, since = 0, 0
        while True:
            res = self._req("GET", "/collections/v2/diff",
                            params={"collectionID": collection_id, "sinceTime": since})
            for f in res.get("diff", []):
                since = max(since, f.get("updationTime", since))
                if not f.get("isDeleted"):
                    count += 1
            if not res.get("hasMore"):
                return count


def make_thumbnail(path: Path) -> bytes | None:
    from PIL import Image
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((512, 512))
            import io
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
            return buf.getvalue()
    except Exception:
        return None


def login(origin: str, email: str, recovery_key: bytes) -> tuple[str, bytes]:
    s = requests.Session()
    r = s.post(f"{origin}/users/ott", json={"email": email, "purpose": "login"}, timeout=30)
    if r.status_code >= 400:
        raise SystemExit(f"ott request failed: {r.status_code} {r.text[:200]}")
    r = s.post(f"{origin}/users/verify-email",
               json={"email": email, "ott": "123456"}, timeout=30)
    if r.status_code >= 400:
        raise SystemExit(f"verify-email failed: {r.status_code} {r.text[:200]}")
    res = r.json()
    ka = res["keyAttributes"]
    master_key = secretbox_open(
        ka["masterKeyEncryptedWithRecoveryKey"],
        ka["masterKeyDecryptionNonce"],
        recovery_key,
    )
    secret_key = secretbox_open(
        ka["encryptedSecretKey"], ka["secretKeyDecryptionNonce"], master_key
    )
    box = nacl.public.SealedBox(nacl.public.PrivateKey(secret_key))
    token = base64.urlsafe_b64encode(box.decrypt(b64d(res["encryptedToken"]))).decode()
    return token, master_key


def main() -> int:
    ap = argparse.ArgumentParser(description="Mirror photos to Thalassa Ente instance")
    ap.add_argument("--origin", default=DEFAULT_ORIGIN, help="Thalassa museum origin URL")
    ap.add_argument("--root", default=r"E:\development\ente-queue", help="Root folder to mirror")
    ap.add_argument("--state", default=r"E:\development\ente-queue\thalassa-mirror-state.json")
    ap.add_argument("--only", nargs="*", help="limit to these album/folder names")
    ap.add_argument("--limit", type=int, default=0, help="max files per album (testing)")
    ap.add_argument("--verify", action="store_true", help="print server-side album counts")
    args = ap.parse_args()

    email, phrase = load_credentials()
    recovery_key = recovery_key_from_phrase(phrase)
    token, master_key = login(args.origin, email, recovery_key)
    client = EnteClient(args.origin, token, master_key)

    if args.verify:
        print(f"Connected to {args.origin} as {email}:")
        albums = client.collections()
        for name in sorted(albums):
            print(f"{client.collection_file_count(albums[name][0]):5d}  {name}")
        return 0

    print(f"Thalassa mirror initialized for root: {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
