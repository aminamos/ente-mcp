# ente-mcp

Unofficial **CLI + MCP** for [Ente](https://ente.com) **Photos**, **Auth**, and **Locker**.

Not affiliated with ente.com / ente-io. This does not reimplement Ente cryptography. Photos uploads go through the official desktop **watch folders**. Auth export/decrypt and account listing shell out to the official [`ente` CLI](https://github.com/ente/ente/tree/main/cli).

## Why

Ente is more than Photos. The official CLI already:

| App | Official `ente` CLI |
|---|---|
| Photos | `ente export` |
| Auth | `ente export` → `ente_auth.txt`; `ente auth decrypt` |
| Locker | `ente account add` / `get-token --app locker` — **no item export** |

Agents still need a local way to **drop files into Photos** when the desktop app is closed. Ente desktop scans watch folders on launch (`deduceEvents`) and uploads anything not in `syncedFiles`. This tool queues into those folders (hardlink, copy fallback) and talks to MCP clients.

## Install

```sh
pip install git+https://github.com/aminamos/ente-mcp.git
```

Or from a checkout:

```sh
uv sync
uv run ente-agent --help
```

Optional: install the official Ente CLI from [GitHub releases](https://github.com/ente/ente/releases?q=tag%3Acli-v0) and put `ente` on `PATH` (or set `ENTE_CLI`).

## CLI (`ente-agent`)

```sh
ente-agent apps
ente-agent status
ente-agent accounts

ente-agent photos watches
ente-agent photos pending
ente-agent photos queue ./shot.jpg --album Inbox
ente-agent photos ensure-watch --folder ~/Ente/Inbox --mapping parent

ente-agent export
ente-agent auth decrypt encrypted.json decrypted.txt
ente-agent locker status

ente-agent museum account
ente-agent museum trash --limit 20
ente-agent museum collections
```

Museum ops talk to the Ente server directly (no desktop needed). Auth is the
official CLI session: set `[museum] email` so `ente account get-token` works,
or export `ENTE_MCP_TOKEN`. Endpoint defaults to `https://api.ente.com`
(`[museum] endpoint` / `ENTE_MCP_MUSEUM` for self-hosted). Only plaintext
server state is used — album/file names stay encrypted and are never
decrypted here; destructive calls (`delete-trash`, `empty-trash`) need
`--confirm`. Sharing someone *new* to an album, restoring trash, and
uploading need E2EE keys, so they stay in the official apps.
```

`collectionMapping=parent` → album name is the parent folder of the file. `root` → one album named after the watch folder.

Ente skips archives, checksums, `txt`, `html`, `xmp`, `db`, and dotfiles — same list as desktop Photos.

`ente export` and desktop watch-folder uploads cannot run at the same time (the machine freezes). `ente-agent export` / `ente_export` stop `etne.exe`/`ente.exe` desktops first and hold `state/export-active` for the run; `scripts/ensure_uploader.py` pauses while that marker's pid is alive (sweeping stale markers), so uploads resume on their own. Only one export runs at a time — a second caller gets `ExportBusy`.

## MCP (`ente-mcp`)

Stdio server. Tools:

| Tool | App |
|---|---|
| `ente_apps` | Photos / Auth / Locker capabilities |
| `ente_status` | Photos desktops: running?, watches, pending |
| `ente_list_watches` | Photos |
| `ente_queue` | Photos |
| `ente_pending` | Photos |
| `ente_ensure_watch` | Photos (refuses if that process is running) |
| `ente_accounts` | official CLI |
| `ente_export` | Photos + Auth via official CLI |
| `ente_auth_decrypt` | Auth (writes a file; does not print TOTP secrets) |
| `ente_locker_status` | Locker accounts; export not supported |
| `ente_account` | Museum account: usage/quota, subscription, locker, 2FA (read-only) |
| `ente_sessions` / `ente_terminate_session` | Museum sessions (tokens redacted) |
| `ente_collections` | Album IDs, types, sharees, public-link flags (names encrypted) |
| `ente_trash` | Trashed file IDs + deletion deadlines |
| `ente_trash_files` | Move files to trash (`{"fileID", "collectionID"}`) |
| `ente_delete_trash` / `ente_empty_trash` | Permanent delete / empty (`confirm=True`) |
| `ente_remove_files` | Bulk-remove files from an album |
| `ente_unshare` / `ente_leave_album` | Sharing management (no E2EE needed) |
| `ente_public_link` | Create/update/delete an album public link |

Example MCP config:

```json
{
  "mcpServers": {
    "ente": {
      "command": "ente-mcp"
    }
  }
}
```

## Config

Optional TOML. First file found wins:

1. `ENTE_MCP_CONFIG`
2. `./config.local.toml` or `./config.toml`
3. checkout `config.local.toml`
4. `%APPDATA%/ente-mcp/config.toml` or `~/.config/ente-mcp/config.toml`

See `config.example.toml`. Multiple desktop profiles (ente.com vs self-hosted) must stay separate — do not merge `%APPDATA%/ente` with another profile.

```toml
default_client = "photos"
ente_cli = "ente"

[clients.photos]
app = "photos"
process = "ente"
profile = "ente"
queue = "~/Ente/Inbox"

[museum]
endpoint = "https://api.ente.com"
email = "you@example.com"
```

Env: `ENTE_CLI`, `ENTE_MCP_CLIENT`, `ENTE_MCP_CONFIG`, `ENTE_MCP_MUSEUM`, `ENTE_MCP_TOKEN`.

Do **not** write `watch-status.json` while that Ente process is running.

## License

MIT.
