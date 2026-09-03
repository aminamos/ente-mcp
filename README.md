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
```

`collectionMapping=parent` → album name is the parent folder of the file. `root` → one album named after the watch folder.

Ente skips archives, checksums, `txt`, `html`, `xmp`, `db`, and dotfiles — same list as desktop Photos.

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
```

Env: `ENTE_CLI`, `ENTE_MCP_CLIENT`, `ENTE_MCP_CONFIG`.

Do **not** write `watch-status.json` while that Ente process is running.

## License

MIT.
