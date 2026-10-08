"""Inventory SELF-HOSTED museum (robusteland): collections + file sizes via API.

Same crawl as inventory_official.py, pointed at the museum origin.
Reads ENTE_MUSEUM_TOKEN env (required) and MUSEUM_API env
(default https://etne.robusteland.box.ca).
Writes state/museum-files.jsonl + state/museum-collections.json.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import inventory_official as base

base.API = os.environ.get("MUSEUM_API", "https://etne.robusteland.box.ca")
base.TOKEN = os.environ.get("ENTE_MUSEUM_TOKEN", "")
base.OUT = r"E:\development\ente-mcp\state\museum-files.jsonl"
base.OUT_COLLS = r"E:\development\ente-mcp\state\museum-collections.json"

if __name__ == "__main__":
    if not base.TOKEN:
        sys.exit("need ENTE_MUSEUM_TOKEN env")
    raise SystemExit(base.main())
