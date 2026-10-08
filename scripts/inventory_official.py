"""Inventory OFFICIAL Ente cloud (api.ente.com): collections + file sizes via API.

Low RAM: streams per-collection diffs.
Reads ENTE_OFFICIAL_TOKEN env (falls back to ENTE_TOKEN for back-compat).
Writes state/official-files.jsonl + state/official-collections.json, prints summary.
Import-safe: entry point is main() (see inventory_museum.py wrapper).
"""
import json
import os
import sys
import time
import urllib.request

TOKEN = os.environ.get("ENTE_OFFICIAL_TOKEN") or os.environ.get("ENTE_TOKEN", "")
API = "https://api.ente.com"
OUT = r"E:\development\ente-mcp\state\official-files.jsonl"
OUT_COLLS = r"E:\development\ente-mcp\state\official-collections.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def call(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data,
        method="POST" if body is not None else "GET",
        headers={"X-Auth-Token": TOKEN,
                 "X-Client-Package": "io.ente.photos.desktop",
                 "X-Client-Version": "1.7.28",
                 "Content-Type": "application/json",
                 "User-Agent": UA})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"  retry {path}: {str(exc)[:100]}", flush=True)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed {path}: {last}")


def main() -> int:
    if not TOKEN:
        print("need ENTE_OFFICIAL_TOKEN env (or ENTE_TOKEN)", file=sys.stderr)
        return 2
    cols = call("/collections")
    collections = cols.get("collections", cols if isinstance(cols, list) else [])
    print(f"collections={len(collections)}", flush=True)
    with open(OUT_COLLS, "w", encoding="utf-8") as cf:
        json.dump(collections, cf)
    print(f"wrote {OUT_COLLS}", flush=True)
    total_files = total_bytes = 0
    skipped = []
    with open(OUT, "w", encoding="utf-8") as f:
        for i, c in enumerate(collections):
            cid = c.get("id")
            since = 0
            n_coll = 0
            try:
                while True:
                    d = call(f"/collections/v2/diff?collectionID={cid}&sinceTime={since}")
                    diff = d.get("diff", [])
                    for file in diff:
                        fid = file.get("id")
                        info = file.get("info") or {}
                        sz = info.get("fileSize") or file.get("fileSize") or 0
                        upd = file.get("updationTime") or 0
                        if isinstance(upd, int) and upd > since:
                            since = upd
                        is_del = bool(file.get("isDeleted", False))
                        f.write(json.dumps({"id": fid, "coll": cid, "size": sz,
                                            "del": is_del, "upd": upd}) + "\n")
                        if not is_del:
                            total_files += 1
                            total_bytes += sz or 0
                        n_coll += 1
                    if not d.get("hasMore"):
                        break
                    time.sleep(0.15)
            except Exception as exc:  # noqa: BLE001 - per-collection tolerance
                print(f"  [{i + 1}/{len(collections)}] coll {cid}: SKIP ({str(exc)[:80]})",
                      flush=True)
                skipped.append(cid)
                continue
            print(f"  [{i + 1}/{len(collections)}] coll {cid}: {n_coll} entries",
                  flush=True)
            time.sleep(0.1)
    print(f"TOTAL files={total_files} GB={total_bytes / (1 << 30):.2f}", flush=True)
    print(f"wrote {OUT}", flush=True)
    if skipped:
        print(f"SKIPPED {len(skipped)} collections: {skipped}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
