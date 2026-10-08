"""Thin museum (Ente server) API client for operator tasks.

Uses only server-visible plaintext: IDs, counts, quotas, share rosters,
public-link flags. Anything needing E2EE (decrypting names/keys, sharing an
album with someone new, restoring trash, uploading) stays out on purpose —
this package does not reimplement Ente cryptography.

Auth: ``X-Auth-Token`` session token from ``ENTE_MCP_TOKEN``, or read from
the official CLI (``ente account get-token``) for the configured museum
account. The token is never included in returned data or error text.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ente_mcp import __version__, official
from ente_mcp.config import Config

DEFAULT_ENDPOINT = "https://api.ente.com"
# api.ente.com sits behind Cloudflare, which 403s requests without a
# User-Agent (error 1010). Identify honestly; no browser masquerading.
USER_AGENT = f"ente-mcp/{__version__}"
BATCH = 1000
MAX_TRASH_PAGES = 20


def museum_endpoint(config: Config) -> str:
    return (config.museum_endpoint or DEFAULT_ENDPOINT).rstrip("/")


def museum_token(config: Config) -> str:
    """Resolve the museum session token without ever logging it."""
    env = os.environ.get("ENTE_MCP_TOKEN", "").strip()
    if env:
        return env
    email = (config.museum_email or "").strip()
    if not email:
        raise ValueError(
            "no museum token: set ENTE_MCP_TOKEN or configure "
            "[museum] email so `ente account get-token` can be used"
        )
    result = official.run_ente(
        config.ente_cli, ["account", "get-token", "--email", email, "--app", "photos"]
    )
    token = (result.get("stdout") or "").strip() if result.get("ok") else ""
    if not token:
        raise ValueError(
            f"could not read museum token for {email!r} via the official ente CLI"
        )
    return token


def _http_json(
    method: str,
    url: str,
    *,
    token: str,
    body: Any = None,
    timeout: int = 60,
) -> tuple[int, Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "X-Auth-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8") or "null"
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8") or "null")
        except (ValueError, OSError):
            detail = None
        message = "request failed"
        if isinstance(detail, dict):
            message = str(detail.get("message") or detail.get("code") or message)
        return exc.code, {"message": message}


def _call(
    config: Config,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: Any = None,
    timeout: int = 60,
) -> tuple[bool, Any]:
    try:
        token = museum_token(config)
    except ValueError as exc:
        return False, {"ok": False, "error": str(exc)}
    url = museum_endpoint(config) + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    try:
        status, data = _http_json(method, url, token=token, body=body, timeout=timeout)
    except (OSError, ValueError) as exc:
        return False, {"ok": False, "error": f"{method} {path} failed: {exc}"}
    if status < 200 or status >= 300:
        message = data.get("message") if isinstance(data, dict) else None
        return False, {
            "ok": False,
            "error": f"{method} {path} -> HTTP {status}: {message or 'request failed'}",
            "status": status,
        }
    return True, data


def _chunks(items: list[Any], size: int = BATCH) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)] or []


def _as_int(value: Any, name: str) -> int:
    number = int(value)
    if number <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return number


def _require_ids(values: list[Any], name: str) -> list[int]:
    ids = [_as_int(v, name) for v in values]
    if not ids:
        raise ValueError(f"{name} is required")
    return ids


def account_overview(config: Config) -> dict[str, Any]:
    """Storage quota/usage, subscription, locker usage, 2FA and delete intel.

    All read-only. Extra sections are best-effort: details/v2 is required,
    the rest report per-section errors without failing the call.
    """
    ok, details = _call(config, "GET", "/users/details/v2")
    if not ok:
        return details
    subscription = details.get("subscription") or {}
    family = details.get("familyData") or {}
    members = family.get("members") or []
    quota = int(subscription.get("storage") or 0) + int(details.get("storageBonus") or 0)
    if members:
        usage = sum(int(m.get("usage") or 0) for m in members)
        quota = int(family.get("storage") or 0) + int(details.get("storageBonus") or 0)
    else:
        usage = int(details.get("usage") or 0)
    out: dict[str, Any] = {
        "ok": True,
        "email": details.get("email"),
        "userID": details.get("id"),
        "usageBytes": usage,
        "quotaBytes": quota,
        "overQuota": quota > 0 and usage > quota,
        "fileCount": details.get("fileCount"),
        "subscription": {
            "productID": subscription.get("productID"),
            "paymentProvider": subscription.get("paymentProvider"),
            "expiryTime": subscription.get("expiryTime"),
        },
        "familyMembers": len(members),
    }
    for key, path in (
        ("locker", "/users/locker-usage"),
        ("twoFactor", "/users/two-factor/status"),
        ("deletion", "/users/deletion-summary"),
    ):
        section_ok, data = _call(config, "GET", path)
        out[key] = data if section_ok else {"error": data.get("error")}
    return out


def sessions_list(config: Config) -> dict[str, Any]:
    """Active museum sessions. Tokens are redacted to their last 4 chars."""
    ok, data = _call(config, "GET", "/users/sessions")
    if not ok:
        return data
    sessions = []
    for item in data.get("sessions") or []:
        token = str(item.get("token") or "")
        sessions.append(
            {
                "tokenSuffix": token[-4:] if token else None,
                "isCurrent": item.get("isCurrent"),
                "ip": item.get("ip"),
                "ua": item.get("prettyUA") or item.get("ua"),
                "creationTime": item.get("creationTime"),
                "lastUsedTime": item.get("lastUsedTime"),
            }
        )
    sessions.sort(key=lambda row: row.get("lastUsedTime") or 0, reverse=True)
    return {"ok": True, "sessions": sessions}


def session_terminate(config: Config, session_token: str) -> dict[str, Any]:
    """Revoke one museum session by its full token (as shown in the web app)."""
    if not (session_token or "").strip():
        return {"ok": False, "error": "session_token is required"}
    ok, data = _call(
        config, "DELETE", "/users/session", query={"token": session_token.strip()}
    )
    if not ok:
        return data
    return {"ok": True, "terminated": True}


def collections_inventory(config: Config) -> dict[str, Any]:
    """Album inventory: IDs, types, share rosters, public-link flags.

    Names stay encrypted (E2EE) and are not decrypted here; cross-reference
    names via an `ente export` if needed.
    """
    ok, data = _call(config, "GET", "/collections/v2", query={"sinceTime": 0})
    if not ok:
        return data
    rows: list[dict[str, Any]] = []
    for change in data.get("collections") or []:
        collection = change.get("collection") or change
        if not isinstance(collection, dict) or collection.get("isDeleted"):
            continue
        owner = collection.get("owner") or {}
        sharees = collection.get("sharees") or []
        links = collection.get("publicURLs") or []
        rows.append(
            {
                "id": collection.get("id"),
                "type": collection.get("type"),
                "ownerID": owner.get("id"),
                "ownerEmail": owner.get("email"),
                "sharees": [
                    {"id": s.get("id"), "email": s.get("email"), "role": s.get("role")}
                    for s in sharees
                ],
                "publicLinks": [
                    {
                        "url": link.get("url"),
                        "validTill": link.get("validTill"),
                        "deviceLimit": link.get("deviceLimit"),
                        "passwordEnabled": link.get("passwordEnabled"),
                        "enableCollect": link.get("enableCollect"),
                        "enableJoin": link.get("enableJoin"),
                        "enableDownload": link.get("enableDownload"),
                    }
                    for link in links
                ],
                "updationTime": collection.get("updationTime"),
                "nameEncrypted": bool(collection.get("encryptedName")),
            }
        )
    # Owner-vs-sharee split needs our user ID; fetch cheaply from details.
    mine = [c for c in rows if not c["sharees"]]
    theirs: list[dict[str, Any]] = []
    ok, details = _call(config, "GET", "/users/details/v2")
    if ok and isinstance(details.get("id"), int):
        mine_id = details["id"]
        mine = [c for c in rows if c.get("ownerID") == mine_id]
        theirs = [c for c in rows if c.get("ownerID") != mine_id]
    return {
        "ok": True,
        "owned": mine,
        "shared": theirs,
        "note": "Album names are end-to-end encrypted; IDs map to names via ente export.",
    }


def trash_overview(config: Config, limit: int = 100) -> dict[str, Any]:
    """Trashed files (IDs + deletion deadlines). Names stay encrypted."""
    items: list[dict[str, Any]] = []
    totals = {"active": 0, "deleted": 0, "restored": 0}
    since_time = 0
    max_updated = 0
    for _ in range(MAX_TRASH_PAGES):
        ok, data = _call(
            config, "GET", "/trash/v2/diff", query={"sinceTime": since_time}
        )
        if not ok:
            return data
        diff = data.get("diff") or []
        if not diff:
            break
        for entry in diff:
            file = entry.get("file") or {}
            max_updated = max(max_updated, int(entry.get("updatedAt") or 0))
            since_time = max(since_time, int(entry.get("updatedAt") or 0))
            if entry.get("isDeleted"):
                totals["deleted"] += 1
                continue
            if entry.get("isRestored"):
                totals["restored"] += 1
                continue
            totals["active"] += 1
            items.append(
                {
                    "fileID": file.get("id"),
                    "collectionID": file.get("collectionID"),
                    "ownerID": file.get("ownerID"),
                    "updatedAt": entry.get("updatedAt"),
                    "deleteBy": entry.get("deleteBy"),
                }
            )
        if not data.get("hasMore"):
            break
    cap = max(0, min(limit, 500))
    return {
        "ok": True,
        "totals": totals,
        "maxUpdatedAt": max_updated,
        "items": items[:cap],
        "note": "Pass maxUpdatedAt as last_updated_at to empty-trash to delete exactly this set.",
    }


def trash_move(config: Config, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Move files to trash. Each item: {"fileID": int, "collectionID": int}."""
    try:
        payload = [
            {
                "fileID": _as_int(item.get("fileID"), "fileID"),
                "collectionID": _as_int(item.get("collectionID"), "collectionID"),
            }
            for item in items
        ]
        if not payload:
            raise ValueError("items is required")
    except (ValueError, TypeError, AttributeError) as exc:
        return {"ok": False, "error": str(exc)}
    trashed = 0
    for chunk in _chunks(payload):
        ok, data = _call(config, "POST", "/files/trash", body={"items": chunk})
        if not ok:
            return {**data, "trashed": trashed}
        trashed += len(chunk)
    return {"ok": True, "trashed": trashed}


def trash_delete(
    config: Config, file_ids: list[Any], *, confirm: bool = False
) -> dict[str, Any]:
    """Permanently delete trashed files. Requires confirm=True."""
    if not confirm:
        return {
            "ok": False,
            "error": "permanent deletion requires confirm=True",
            "hint": "List with ente_trash first, then confirm the file IDs.",
        }
    try:
        ids = _require_ids(file_ids, "file_ids")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    deleted = 0
    for chunk in _chunks(ids):
        ok, data = _call(config, "POST", "/trash/delete", body={"fileIDs": chunk})
        if not ok:
            return {**data, "deleted": deleted}
        deleted += len(chunk)
    return {"ok": True, "deleted": deleted}


def trash_empty(
    config: Config, *, confirm: bool = False, last_updated_at: int = 0
) -> dict[str, Any]:
    """Empty trash up to last_updated_at (0 = everything). Requires confirm."""
    if not confirm:
        return {
            "ok": False,
            "error": "emptying trash requires confirm=True",
            "hint": "List with ente_trash first; pass its maxUpdatedAt as last_updated_at.",
        }
    ok, data = _call(
        config, "POST", "/trash/empty", body={"lastUpdatedAt": int(last_updated_at)}
    )
    if not ok:
        return data
    return {"ok": True, "emptied": True, "lastUpdatedAt": int(last_updated_at)}


def collection_remove_files(
    config: Config, collection_id: Any, file_ids: list[Any]
) -> dict[str, Any]:
    """Remove files from an album (bulk). Files stay in the library."""
    try:
        cid = _as_int(collection_id, "collection_id")
        ids = _require_ids(file_ids, "file_ids")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    removed = 0
    for chunk in _chunks(ids):
        ok, data = _call(
            config,
            "POST",
            "/collections/v3/remove-files",
            body={"collectionID": cid, "fileIDs": chunk},
        )
        if not ok:
            return {**data, "removed": removed}
        removed += len(chunk)
    return {"ok": True, "collectionID": cid, "removed": removed}


def collection_unshare(
    config: Config, collection_id: Any, email: str
) -> dict[str, Any]:
    """Remove one sharee from an album. (Sharing new people needs E2EE keys.)"""
    try:
        cid = _as_int(collection_id, "collection_id")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not (email or "").strip():
        return {"ok": False, "error": "email is required"}
    ok, data = _call(
        config,
        "POST",
        "/collections/unshare",
        body={"collectionID": cid, "email": email.strip()},
    )
    if not ok:
        return data
    return {"ok": True, "collectionID": cid, "unshared": email.strip()}


def collection_leave(config: Config, collection_id: Any) -> dict[str, Any]:
    """Leave a shared album."""
    try:
        cid = _as_int(collection_id, "collection_id")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    ok, data = _call(config, "POST", f"/collections/leave/{cid}")
    if not ok:
        return data
    return {"ok": True, "left": cid}


def public_link(
    config: Config,
    collection_id: Any,
    action: str,
    *,
    valid_till: int = 0,
    device_limit: int = 0,
    enable_collect: bool = False,
    enable_join: bool = False,
    enable_download: bool = True,
) -> dict[str, Any]:
    """Create, update, or delete an album's public link (share-url).

    create: optional valid_till (epoch micros, 0 = forever), device_limit
    (0 = unlimited), enable_collect (allow uploads into the album),
    enable_join, enable_download. update: same knobs. delete: no knobs.
    """
    try:
        cid = _as_int(collection_id, "collection_id")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    verb = (action or "").strip().lower()
    if verb == "create":
        body: dict[str, Any] = {
            "collectionID": cid,
            "enableComment": True,
            "enableCollect": enable_collect,
            "enableJoin": enable_join,
            "enableDownload": enable_download,
        }
        if valid_till > 0:
            body["validTill"] = int(valid_till)
        if device_limit > 0:
            body["deviceLimit"] = int(device_limit)
        ok, data = _call(config, "POST", "/collections/share-url", body=body)
        if not ok:
            return data
        result = data.get("result") or data
        return {"ok": True, "action": "create", "collectionID": cid, "link": result}
    if verb == "update":
        body = {
            "collectionID": cid,
            "validTill": int(valid_till),
            "deviceLimit": int(device_limit),
            "enableCollect": enable_collect,
            "enableJoin": enable_join,
            "enableDownload": enable_download,
        }
        ok, data = _call(config, "PUT", "/collections/share-url", body=body)
        if not ok:
            return data
        result = data.get("result") or data
        return {"ok": True, "action": "update", "collectionID": cid, "link": result}
    if verb == "delete":
        ok, data = _call(config, "DELETE", f"/collections/share-url/{cid}")
        if not ok:
            return data
        return {"ok": True, "action": "delete", "collectionID": cid}
    return {
        "ok": False,
        "error": f"unknown action {action!r}; use create, update, or delete",
    }
