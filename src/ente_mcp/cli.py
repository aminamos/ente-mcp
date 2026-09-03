from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from ente_mcp import __version__, official, photos
from ente_mcp.config import get_client, load_config
from ente_mcp.process import process_running


def _print(data: Any, as_json: bool) -> int:
    if as_json or not isinstance(data, dict):
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if not isinstance(data, dict) or data.get("ok", True) else 1
    ok = data.get("ok")
    if ok is False:
        err = data.get("error") or data.get("reason") or "failed"
        print(err, file=sys.stderr)
        hint = data.get("hint")
        if hint:
            print(hint, file=sys.stderr)
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1
    json.dump(data, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ente-agent",
        description="Unofficial CLI for Ente Photos, Auth, and Locker.",
    )
    parser.add_argument("--json", action="store_true", help="JSON on stdout (always on; kept for scripts)")
    parser.add_argument("--version", action="store_true", help="Print ente-agent version")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("mcp", help="Run the MCP stdio server")
    sub.add_parser("apps", help="Photos / Auth / Locker capabilities")
    sub.add_parser("status", help="Photos desktop watch folders + official CLI")
    sub.add_parser("accounts", help="Official ente CLI accounts")

    photos_p = sub.add_parser("photos", help="Desktop watch-folder uploads")
    photos_sub = photos_p.add_subparsers(dest="photos_cmd", required=True)
    watches = photos_sub.add_parser("watches", help="List watch folders")
    watches.add_argument("--client", default="")
    pending = photos_sub.add_parser("pending", help="Files not yet marked synced")
    pending.add_argument("--client", default="")
    pending.add_argument("--limit", type=int, default=50)
    ensure = photos_sub.add_parser("ensure-watch", help="Register a watch folder if the app is closed")
    ensure.add_argument("--client", default="")
    ensure.add_argument("--folder", default="")
    ensure.add_argument("--mapping", choices=("parent", "root"), default="parent")
    queue = photos_sub.add_parser("queue", help="Hardlink or copy files into a watch-folder album")
    queue.add_argument("paths", nargs="+")
    queue.add_argument("--album", default="Inbox")
    queue.add_argument("--client", default="")
    queue.add_argument("--watch-folder", default="")

    export_p = sub.add_parser("export", help="Official ente export (Photos + Auth; not Locker)")
    export_p.add_argument("--shared", dest="shared", action="store_true", default=True)
    export_p.add_argument("--no-shared", dest="shared", action="store_false")
    export_p.add_argument("--hidden", dest="hidden", action="store_true", default=True)
    export_p.add_argument("--no-hidden", dest="hidden", action="store_false")
    export_p.add_argument("--albums", default="")
    export_p.add_argument("--emails", default="")
    export_p.add_argument("--exclude-albums", default="")

    auth_p = sub.add_parser("auth", help="Ente Auth via official CLI")
    auth_sub = auth_p.add_subparsers(dest="auth_cmd", required=True)
    decrypt = auth_sub.add_parser("decrypt", help="Decrypt an Auth export file")
    decrypt.add_argument("input_path")
    decrypt.add_argument("output_path")
    decrypt.add_argument("-p", "--password", default="")
    auth_sub.add_parser("export", help="Run official ente export (Auth accounts included)")

    locker_p = sub.add_parser("locker", help="Ente Locker via official CLI")
    locker_sub = locker_p.add_subparsers(dest="locker_cmd", required=True)
    locker_sub.add_parser("status", help="Locker accounts; export is not supported")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version or args.cmd is None:
        if args.cmd is None and not args.version:
            parser.print_help()
            return 0
        print(__version__)
        return 0

    if args.cmd == "mcp":
        from ente_mcp.server import main as mcp_main

        mcp_main()
        return 0

    config = load_config()
    as_json = True

    if args.cmd == "apps":
        data = official.apps_status(config.ente_cli)
        data["defaultClient"] = config.default_client
        data["configPath"] = str(config.config_path) if config.config_path else None
        data["clients"] = {
            name: {
                "app": client.app,
                "process": client.process,
                "profile": client.profile,
                "queue": str(client.queue) if client.queue else None,
                "running": process_running(client.process),
            }
            for name, client in config.clients.items()
        }
        return _print(data, as_json)

    if args.cmd == "status":
        desktops = {}
        for name, client in config.clients.items():
            if client.app != "photos":
                continue
            desktops[name] = photos.watch_summary(client)
        return _print(
            {
                "defaultClient": config.default_client,
                "configPath": str(config.config_path) if config.config_path else None,
                "photos": desktops,
                "officialCli": official.find_ente_cli(config.ente_cli),
            },
            as_json,
        )

    if args.cmd == "accounts":
        return _print(official.list_accounts(config.ente_cli), as_json)

    if args.cmd == "photos":
        client = get_client(config, args.client or None)
        if args.photos_cmd == "watches":
            return _print(photos.watch_summary(client), as_json)
        if args.photos_cmd == "pending":
            return _print(photos.pending_files(client, limit=args.limit), as_json)
        if args.photos_cmd == "ensure-watch":
            return _print(
                photos.ensure_watch(client, folder=args.folder, collection_mapping=args.mapping),
                as_json,
            )
        if args.photos_cmd == "queue":
            return _print(
                photos.queue_files(
                    client,
                    args.paths,
                    album=args.album,
                    watch_folder=args.watch_folder,
                ),
                as_json,
            )

    if args.cmd == "export":
        albums = [p for p in args.albums.split(",") if p] if args.albums else None
        emails = [p for p in args.emails.split(",") if p] if args.emails else None
        exclude = [p for p in args.exclude_albums.split(",") if p] if args.exclude_albums else None
        return _print(
            official.export_data(
                config.ente_cli,
                shared=args.shared,
                hidden=args.hidden,
                albums=albums,
                emails=emails,
                exclude_albums=exclude,
            ),
            as_json,
        )

    if args.cmd == "auth":
        if args.auth_cmd == "decrypt":
            return _print(
                official.auth_decrypt(
                    config.ente_cli,
                    args.input_path,
                    args.output_path,
                    password=args.password,
                ),
                as_json,
            )
        if args.auth_cmd == "export":
            return _print(official.export_data(config.ente_cli), as_json)

    if args.cmd == "locker" and args.locker_cmd == "status":
        listed = official.list_accounts(config.ente_cli)
        if not listed.get("ok"):
            listed["officialExport"] = False
            return _print(listed, as_json)
        accounts = [a for a in listed.get("accounts") or [] if (a.get("app") or "").lower() == "locker"]
        return _print(
            {
                "ok": True,
                "app": "locker",
                "officialExport": False,
                "accounts": accounts,
                "note": (
                    "Official ente CLI can add a locker account and get-token. "
                    "Locker item export is not implemented."
                ),
            },
            as_json,
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
