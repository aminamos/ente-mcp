from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ente_mcp.config import Config, get_client, load_config
from ente_mcp import official, photos
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
    """Run official ente export. Photos albums and Auth codes; Locker is skipped by ente CLI."""
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


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
