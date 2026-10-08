from __future__ import annotations

from typing import Any

import pytest

from ente_mcp import museum
from ente_mcp.config import Config


def make_config(**overrides: Any) -> Config:
    base: dict[str, Any] = {
        "default_client": "photos",
        "ente_cli": "ente",
        "clients": {},
        "config_path": None,
        "museum_endpoint": "https://museum.example",
        "museum_email": "op@example.com",
    }
    base.update(overrides)
    return Config(**base)  # type: ignore[arg-type]


@pytest.fixture()
def token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENTE_MCP_TOKEN", "test-token")
    monkeypatch.delenv("ENTE_MCP_MUSEUM", raising=False)


def fake_http(
    monkeypatch: pytest.MonkeyPatch, routes: dict[tuple[str, str], tuple[int, Any]]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def handler(
        method: str, url: str, *, token: str, body: Any = None, timeout: int = 60
    ) -> tuple[int, Any]:
        assert token == "test-token", "session token must reach the transport"
        assert url.startswith("https://museum.example/")
        path = url[len("https://museum.example") :].split("?", 1)[0]
        calls.append({"method": method, "path": path, "body": body})
        if (method, path) not in routes:
            raise AssertionError(f"unexpected call {method} {path}")
        return routes[(method, path)]

    monkeypatch.setattr(museum, "_http_json", handler)
    return calls


def test_token_prefers_env(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    assert museum.museum_token(make_config()) == "test-token"


def test_token_missing_without_email_or_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENTE_MCP_TOKEN", raising=False)
    with pytest.raises(ValueError, match="ENTE_MCP_TOKEN"):
        museum.museum_token(make_config(museum_email=""))


def test_error_shapes_never_carry_token(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    def boom(*args: Any, **kwargs: Any) -> tuple[int, Any]:
        raise AssertionError("no transport without token")

    monkeypatch.setattr(museum, "_http_json", boom)
    monkeypatch.delenv("ENTE_MCP_TOKEN", raising=False)
    result = museum.account_overview(make_config(museum_email=""))
    assert result["ok"] is False
    assert "test-token" not in str(result)


def test_http_error_mapping(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    calls = fake_http(monkeypatch, {("GET", "/users/sessions"): (401, {"code": 401})})
    result = museum.sessions_list(make_config())
    assert result["ok"] is False
    assert "401" in result["error"]
    assert calls[0]["path"] == "/users/sessions"


def test_account_overview_math(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    fake_http(
        monkeypatch,
        {
            ("GET", "/users/details/v2"): (
                200,
                {
                    "id": 7,
                    "email": "op@example.com",
                    "usage": 10,
                    "fileCount": 3,
                    "subscription": {
                        "productID": "free",
                        "storage": 100,
                        "expiryTime": 0,
                        "paymentProvider": "stripe",
                    },
                    "storageBonus": 5,
                },
            ),
            ("GET", "/users/locker-usage"): (200, {"usage": 1}),
            ("GET", "/users/two-factor/status"): (200, {"isEnabled": True}),
            ("GET", "/users/deletion-summary"): (200, {"fileCount": 3}),
        },
    )
    result = museum.account_overview(make_config())
    assert result["ok"] is True
    assert result["usageBytes"] == 10
    assert result["quotaBytes"] == 105
    assert result["overQuota"] is False
    assert result["locker"] == {"usage": 1}
    assert result["twoFactor"] == {"isEnabled": True}


def test_account_overview_family_quota(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    fake_http(
        monkeypatch,
        {
            ("GET", "/users/details/v2"): (
                200,
                {
                    "id": 7,
                    "email": "op@example.com",
                    "usage": 999,
                    "subscription": {"productID": "paid", "storage": 0},
                    "storageBonus": 0,
                    "familyData": {
                        "storage": 50,
                        "members": [{"usage": 30}, {"usage": 25}],
                    },
                },
            ),
            ("GET", "/users/locker-usage"): (500, None),
            ("GET", "/users/two-factor/status"): (200, {}),
            ("GET", "/users/deletion-summary"): (200, {}),
        },
    )
    result = museum.account_overview(make_config())
    assert result["usageBytes"] == 55
    assert result["quotaBytes"] == 50
    assert result["overQuota"] is True
    assert result["familyMembers"] == 2
    assert "error" in result["locker"]


def test_sessions_redact_and_sort(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    fake_http(
        monkeypatch,
        {
            ("GET", "/users/sessions"): (
                200,
                {
                    "sessions": [
                        {
                            "token": "aaaabbbbcccc",
                            "creationTime": 1,
                            "ip": "1.2.3.4",
                            "ua": "x",
                            "prettyUA": "Web",
                            "lastUsedTime": 5,
                        },
                        {
                            "token": "zzzz",
                            "creationTime": 2,
                            "ip": "5.6.7.8",
                            "ua": "y",
                            "prettyUA": "App",
                            "lastUsedTime": 9,
                        },
                    ]
                },
            )
        },
    )
    result = museum.sessions_list(make_config())
    assert [s["tokenSuffix"] for s in result["sessions"]] == ["zzzz", "cccc"]
    assert "aaaabbbbcccc" not in str(result)


def test_trash_overview_paginates(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    page1 = {
        "diff": [
            {
                "file": {"id": 1, "collectionID": 11, "ownerID": 7},
                "isDeleted": False,
                "isRestored": False,
                "updatedAt": 100,
                "deleteBy": 200,
            },
            {
                "file": {"id": 2, "collectionID": 11, "ownerID": 7},
                "isDeleted": True,
                "isRestored": False,
                "updatedAt": 120,
                "deleteBy": 220,
            },
        ],
        "hasMore": True,
    }
    page2 = {
        "diff": [
            {
                "file": {"id": 3, "collectionID": 12, "ownerID": 7},
                "isDeleted": False,
                "isRestored": True,
                "updatedAt": 150,
                "deleteBy": 250,
            }
        ],
        "hasMore": False,
    }
    seen: list[str] = []

    def handler(
        method: str, url: str, *, token: str, body: Any = None, timeout: int = 60
    ) -> tuple[int, Any]:
        seen.append(url)
        return (200, page1) if len(seen) == 1 else (200, page2)

    monkeypatch.setattr(museum, "_http_json", handler)
    result = museum.trash_overview(make_config(), limit=10)
    assert result["totals"] == {"active": 1, "deleted": 1, "restored": 1}
    assert result["maxUpdatedAt"] == 150
    assert [i["fileID"] for i in result["items"]] == [1]
    assert "sinceTime=0" in seen[0]


def test_trash_delete_and_empty_need_confirm(token: None) -> None:
    config = make_config()
    assert museum.trash_delete(config, [1], confirm=False)["ok"] is False
    assert museum.trash_empty(config, confirm=False)["ok"] is False


def test_trash_move_batches(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    calls = fake_http(monkeypatch, {("POST", "/files/trash"): (200, {})})
    items = [{"fileID": i + 1, "collectionID": 9} for i in range(2500)]
    result = museum.trash_move(make_config(), items)
    assert result == {"ok": True, "trashed": 2500}
    assert [len(c["body"]["items"]) for c in calls] == [1000, 1000, 500]


def test_collections_inventory_splits_owner(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    def coll(cid: int, owner: int) -> dict[str, Any]:
        return {
            "id": cid,
            "type": "album",
            "owner": {"id": owner, "email": f"u{owner}@x.y"},
            "encryptedKey": "k",
            "encryptedName": "n",
            "sharees": [],
            "publicURLs": [
                {"url": "https://albums.ente.com/?t=abc", "validTill": 0}
            ],
            "updationTime": 1,
        }

    fake_http(
        monkeypatch,
        {
            ("GET", "/collections/v2"): (
                200,
                {"collections": [coll(1, 7), coll(2, 8), {"isDeleted": True}]},
            ),
            ("GET", "/users/details/v2"): (200, {"id": 7}),
        },
    )
    result = museum.collections_inventory(make_config())
    assert [c["id"] for c in result["owned"]] == [1]
    assert [c["id"] for c in result["shared"]] == [2]
    assert result["owned"][0]["publicLinks"][0]["url"].endswith("?t=abc")


def test_public_link_validation(token: None) -> None:
    config = make_config()
    assert museum.public_link(config, 1, "bogus")["ok"] is False
    assert museum.public_link(config, 0, "delete")["ok"] is False


def test_public_link_create_body(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    calls = fake_http(
        monkeypatch,
        {("POST", "/collections/share-url"): (200, {"result": {"url": "u"}})},
    )
    result = museum.public_link(
        make_config(), 42, "create", device_limit=3, enable_collect=True
    )
    assert result == {
        "ok": True,
        "action": "create",
        "collectionID": 42,
        "link": {"url": "u"},
    }
    assert calls[0]["body"] == {
        "collectionID": 42,
        "enableComment": True,
        "enableCollect": True,
        "enableJoin": False,
        "enableDownload": True,
        "deviceLimit": 3,
    }


def test_unshare_leave_remove_paths(
    monkeypatch: pytest.MonkeyPatch, token: None
) -> None:
    calls = fake_http(
        monkeypatch,
        {
            ("POST", "/collections/unshare"): (200, {}),
            ("POST", "/collections/leave/9"): (200, {}),
            ("POST", "/collections/v3/remove-files"): (200, {}),
        },
    )
    config = make_config()
    assert museum.collection_unshare(config, 8, "pal@example.com")["ok"] is True
    assert museum.collection_leave(config, 9) == {"ok": True, "left": 9}
    assert museum.collection_remove_files(config, 8, [1, 2])["removed"] == 2
    assert museum.collection_unshare(config, 8, "  ")["ok"] is False
    assert [c["path"] for c in calls] == [
        "/collections/unshare",
        "/collections/leave/9",
        "/collections/v3/remove-files",
    ]
