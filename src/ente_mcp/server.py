from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ente_mcp.config import Config, get_client, load_config
from ente_mcp import museum, official, photos
from ente_mcp.process import process_running

mcp = FastMCP(
    "ente",
    instructions=(
        "Unofficial Ente helper for Photos, Auth, and Locker. "
        "Photos: queue files into desktop watch folders even when the app is closed "
        "(collectionMapping=parent means album = parent folder name). "
        "Auth: wrap the official ente CLI export and auth decrypt; never print TOTP secrets. "
        "Locker: official CLI can attach a locker account; item export is not supported. "
        "Do not merge separate desktop profiles. Do not edit watch-status.json while that app is running."
    ),
)


def _cfg() -> Config:
    return load_config()


@mcp.tool()
def ente_apps() -> dict[str, Any]:
    """What this helper can do for Photos, Auth, and Locker, plus official CLI accounts."""
    config = _cfg()
    status = official.apps_status(config.ente_cli)
    status["defaultClient"] = config.default_client
    status["configPath"] = str(config.config_path) if config.config_path else None
    status["clients"] = {
        name: {
            "app": client.app,
            "process": client.process,
            "profile": client.profile,
            "queue": str(client.queue) if client.queue else None,
            "running": process_running(client.process),
        }
        for name, client in config.clients.items()
    }
    return status


@mcp.tool()
def ente_status() -> dict[str, Any]:
    """Desktop running state and Photos watch-folder summaries for every configured client."""
    config = _cfg()
    desktops: dict[str, Any] = {}
    for name, client in config.clients.items():
        if client.app != "photos":
            continue
        desktops[name] = photos.watch_summary(client)
    return {
        "defaultClient": config.default_client,
        "configPath": str(config.config_path) if config.config_path else None,
        "photos": desktops,
        "officialCli": official.find_ente_cli(config.ente_cli),
        "note": (
            "Files copied into a watched Photos folder upload when that Ente app is next open. "
            "Auth and Locker use the official ente CLI, not watch folders."
        ),
    }


@mcp.tool()
def ente_list_watches(client: str = "") -> dict[str, Any]:
    """List Ente Photos watch folders and album mapping for one desktop profile."""
    config = _cfg()
    return photos.watch_summary(get_client(config, client or None))


@mcp.tool()
def ente_ensure_watch(
    client: str = "",
    folder: str = "",
    collection_mapping: str = "parent",
) -> dict[str, Any]:
    """Register a Photos watch folder in watch-status.json. Refuses if that Ente app is running."""
    config = _cfg()
    return photos.ensure_watch(
        get_client(config, client or None),
        folder=folder,
        collection_mapping=collection_mapping,
    )


@mcp.tool()
def ente_queue(
    paths: list[str],
    album: str = "Inbox",
    client: str = "",
    watch_folder: str = "",
) -> dict[str, Any]:
    """Copy or hardlink files into an Ente Photos watch-folder album. Works while Ente is closed."""
    config = _cfg()
    return photos.queue_files(
        get_client(config, client or None),
        paths,
        album=album,
        watch_folder=watch_folder,
    )


@mcp.tool()
def ente_pending(client: str = "", limit: int = 50) -> dict[str, Any]:
    """List media in Photos watch folders that Ente has not marked synced yet."""
    config = _cfg()
    return photos.pending_files(get_client(config, client or None), limit=limit)


@mcp.tool()
def ente_accounts() -> dict[str, Any]:
    """List accounts configured in the official ente CLI (Photos, Auth, Locker)."""
    return official.list_accounts(_cfg().ente_cli)


@mcp.tool()
def ente_export(
    shared: bool = True,
    hidden: bool = True,
    albums: list[str] | None = None,
    emails: list[str] | None = None,
    exclude_albums: list[str] | None = None,
) -> dict[str, Any]:
    """Run official ente export. Photos albums and Auth codes; Locker is skipped by ente CLI.
    Desktop uploaders (etne/ente) are stopped first and resume via ensure_uploader after."""
    return official.export_data(
        _cfg().ente_cli,
        shared=shared,
        hidden=hidden,
        albums=albums,
        emails=emails,
        exclude_albums=exclude_albums,
    )


@mcp.tool()
def ente_auth_decrypt(input_path: str, output_path: str, password: str = "") -> dict[str, Any]:
    """Decrypt an Ente Auth export file via the official ente CLI. Writes to output_path; does not print secrets."""
    return official.auth_decrypt(_cfg().ente_cli, input_path, output_path, password=password)


@mcp.tool()
def ente_locker_status() -> dict[str, Any]:
    """Locker accounts on the official ente CLI. Item export is not supported."""
    listed = official.list_accounts(_cfg().ente_cli)
    if not listed.get("ok"):
        listed["app"] = "locker"
        listed["officialExport"] = False
        return listed
    accounts = [a for a in listed.get("accounts") or [] if (a.get("app") or "").lower() == "locker"]
    return {
        "ok": True,
        "app": "locker",
        "officialExport": False,
        "accounts": accounts,
        "note": (
            "Add a locker account with `ente account add` and choose locker. "
            "Token: `ente account get-token --app locker --email you@domain`. "
            "There is no locker item export in the official CLI yet."
        ),
    }


@mcp.tool()
def ente_account() -> dict[str, Any]:
    """Museum account intel: storage usage/quota, subscription, locker usage, 2FA status. Read-only."""
    return museum.account_overview(_cfg())


@mcp.tool()
def ente_sessions() -> dict[str, Any]:
    """List active museum sessions (tokens redacted). Read-only."""
    return museum.sessions_list(_cfg())


@mcp.tool()
def ente_terminate_session(session_token: str) -> dict[str, Any]:
    """Revoke one museum session by its full token (copy it from the Ente web app)."""
    return museum.session_terminate(_cfg(), session_token)


@mcp.tool()
def ente_collections() -> dict[str, Any]:
    """Album inventory: IDs, types, share rosters, public-link flags. Names stay encrypted. Read-only."""
    return museum.collections_inventory(_cfg())


@mcp.tool()
def ente_trash(limit: int = 100) -> dict[str, Any]:
    """List trashed files (IDs + deletion deadlines). Read-only."""
    return museum.trash_overview(_cfg(), limit=limit)


@mcp.tool()
def ente_trash_files(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Move files to trash. Each item: {"fileID": int, "collectionID": int}."""
    return museum.trash_move(_cfg(), items)


@mcp.tool()
def ente_delete_trash(file_ids: list[int], confirm: bool = False) -> dict[str, Any]:
    """Permanently delete trashed files. Requires confirm=True."""
    return museum.trash_delete(_cfg(), file_ids, confirm=confirm)


@mcp.tool()
def ente_empty_trash(confirm: bool = False, last_updated_at: int = 0) -> dict[str, Any]:
    """Empty trash up to last_updated_at (0 = everything; ente_trash reports maxUpdatedAt). Requires confirm=True."""
    return museum.trash_empty(_cfg(), confirm=confirm, last_updated_at=last_updated_at)


@mcp.tool()
def ente_remove_files(collection_id: int, file_ids: list[int]) -> dict[str, Any]:
    """Remove files from an album in bulk. Files stay in the library."""
    return museum.collection_remove_files(_cfg(), collection_id, file_ids)


@mcp.tool()
def ente_unshare(collection_id: int, email: str) -> dict[str, Any]:
    """Remove one sharee from an album."""
    return museum.collection_unshare(_cfg(), collection_id, email)


@mcp.tool()
def ente_leave_album(collection_id: int) -> dict[str, Any]:
    """Leave a shared album."""
    return museum.collection_leave(_cfg(), collection_id)


@mcp.tool()
def ente_public_link(
    collection_id: int,
    action: str = "create",
    valid_till: int = 0,
    device_limit: int = 0,
    enable_collect: bool = False,
    enable_join: bool = False,
    enable_download: bool = True,
) -> dict[str, Any]:
    """Create, update, or delete an album's public link. action is create, update, or delete."""
    return museum.public_link(
        _cfg(),
        collection_id,
        action,
        valid_till=valid_till,
        device_limit=device_limit,
        enable_collect=enable_collect,
        enable_join=enable_join,
        enable_download=enable_download,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
