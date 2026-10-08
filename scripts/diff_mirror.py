"""Diff official vs museum inventories: are the two libraries mirrored?

Inputs (read-only):
  state/official-files.jsonl   from inventory_official.py (ENTE_OFFICIAL_TOKEN)
  state/museum-files.jsonl     from inventory_museum.py   (ENTE_MUSEUM_TOKEN)

How it compares: file IDs differ across servers and collection names are
E2E-encrypted, so this joins collections by (live_file_count, live_bytes)
fingerprint and compares whole-library live totals. A file counts as LIVE if
any entry for its id has del=false (moved files appear as del=true under the
old collection plus live under the new one).

Caveats printed in the report: official trash is not inventoried; the 158
quarantined files are a known gap (counted from the quarantine dir).
Writes state/mirror-diff.json. Exit 0 after printing the verdict.
"""
import json
import os
import sys

STATE = r"E:\development\ente-mcp\state"
OFFICIAL = os.path.join(STATE, "official-files.jsonl")
MUSEUM = os.path.join(STATE, "museum-files.jsonl")
OUT = os.path.join(STATE, "mirror-diff.json")
QUARANTINE_DIR = os.path.join(r"E:\development\ente-queue-staging", "_unuploadable")


def load(path):
    """Return (live_by_coll, live_count, live_bytes, stats).

    live_by_coll: coll_id -> [count, bytes] over deduplicated live files.
    """
    seen_lines = set()
    per_id = {}  # id -> {"live": [(coll, size)], "del_only": bool}
    raw_lines = bad = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw_lines += 1
            if line in seen_lines:  # exact dup (dual-writer safety)
                continue
            seen_lines.add(line)
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            fid = o.get("id")
            e = per_id.setdefault(fid, {"live": [], "any": 0})
            e["any"] += 1
            if not o.get("del", False):
                e["live"].append((o.get("coll"), o.get("size") or 0))
    live_by_coll = {}
    live_count = live_bytes = multi_live = 0
    for fid, e in per_id.items():
        if not e["live"]:
            continue
        live_count += 1
        if len(e["live"]) > 1:
            multi_live += 1
        coll, size = max(e["live"], key=lambda t: t[1])
        live_bytes += size
        c = live_by_coll.setdefault(coll, [0, 0])
        c[0] += 1
        c[1] += size
    stats = {"raw_lines": raw_lines, "bad_lines": bad,
             "distinct_ids": len(per_id), "multi_live_ids": multi_live}
    return live_by_coll, live_count, live_bytes, stats


def quarantine_size():
    n = b = 0
    for root, _dirs, files in os.walk(QUARANTINE_DIR):
        for fn in files:
            if fn.startswith("."):
                continue
            try:
                b += os.path.getsize(os.path.join(root, fn))
                n += 1
            except OSError:
                continue
    return n, b


def main() -> int:
    missing = [p for p in (OFFICIAL, MUSEUM) if not os.path.exists(p)]
    if missing:
        print("missing inventory output; run the inventory scripts first:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        return 2
    o_coll, o_n, o_b, o_stats = load(OFFICIAL)
    m_coll, m_n, m_b, m_stats = load(MUSEUM)
    q_n, q_b = quarantine_size()

    def fingerprint(by_coll):
        fp = {}
        for cid, (n, b) in by_coll.items():
            fp.setdefault((n, b), []).append(cid)
        return fp

    o_fp, m_fp = fingerprint(o_coll), fingerprint(m_coll)
    matched, ambiguous, o_only, m_only = [], [], [], []
    for key in sorted(set(o_fp) | set(m_fp)):
        o_ids, m_ids = o_fp.get(key, []), m_fp.get(key, [])
        if o_ids and m_ids and len(o_ids) == 1 and len(m_ids) == 1:
            matched.append({"count": key[0], "bytes": key[1],
                            "official_coll": o_ids[0], "museum_coll": m_ids[0]})
        elif o_ids and m_ids:
            ambiguous.append({"count": key[0], "bytes": key[1],
                              "official_colls": o_ids, "museum_colls": m_ids})
        elif o_ids:
            o_only.append({"count": key[0], "bytes": key[1], "official_colls": o_ids})
        else:
            m_only.append({"count": key[0], "bytes": key[1], "museum_colls": m_ids})

    gb = lambda b: round(b / (1 << 30), 2)
    report = {
        "official": {"live_files": o_n, "live_gb": gb(o_b),
                     "collections": len(o_coll), **o_stats},
        "museum": {"live_files": m_n, "live_gb": gb(m_b),
                   "collections": len(m_coll), **m_stats},
        "quarantine": {"files": q_n, "gb": gb(q_b)},
        "delta_files": m_n - o_n,
        "delta_gb": gb(m_b - o_b),
        "matched_collections": len(matched),
        "ambiguous_fingerprints": ambiguous,
        "official_only": o_only,
        "museum_only": m_only,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)

    print(f"official: {o_n} live files / {gb(o_b)} GB across {len(o_coll)} collections")
    print(f"museum:   {m_n} live files / {gb(m_b)} GB across {len(m_coll)} collections")
    print(f"quarantine (known gap): {q_n} files / {gb(q_b)} GB")
    print(f"delta museum-official: {m_n - o_n:+d} files / {gb(m_b - o_b):+.2f} GB")
    print(f"collections matched by fingerprint: {len(matched)}; "
          f"ambiguous: {len(ambiguous)}; official-only: {len(o_only)}; "
          f"museum-only: {len(m_only)}")
    if ambiguous:
        print("ambiguous fingerprints (same count+bytes, needs name-level check):")
        for a in ambiguous[:10]:
            print(f"  files={a['count']} bytes={a['bytes']}")
    if o_only:
        print("official-only fingerprints (possibly missing from museum):")
        for a in o_only[:10]:
            print(f"  files={a['count']} bytes={a['bytes']} colls={a['official_colls'][:3]}")
    if m_only:
        print("museum-only fingerprints (extras or pre-existing albums):")
        for a in m_only[:10]:
            print(f"  files={a['count']} bytes={a['bytes']} colls={a['museum_colls'][:3]}")
    clean = not ambiguous and not o_only
    print("VERDICT: " + ("MIRROR LIKELY COMPLETE (verify counts above)"
                         if clean else "NEEDS REVIEW (see unmatched above)"))
    print("caveats: official trash not inventoried; collection names are "
          "E2E-encrypted (fingerprint join only); deduped by file id.")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
