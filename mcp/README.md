# ente-mcp

Unofficial **CLI + MCP** for Ente **Photos**, **Auth**, and **Locker**. Lives in this snapshot of [ente/ente](https://github.com/ente/ente). Not affiliated with ente.com.

The official Go CLI is in [`../cli`](../cli). This package:

- queues files into **Photos** desktop watch folders while the app is closed
- wraps `ente export` and `ente auth decrypt` for **Auth**
- reports **Locker** accounts (`ente account` supports `--app locker`; item export is not implemented in the official CLI)

## Install

```sh
cd mcp
pip install .
```

- MCP stdio: `ente-mcp`
- CLI: `ente-agent`

Optional: build the official CLI from `../cli` (`go build -o bin/ente main.go`) and put it on `PATH`, or set `ENTE_CLI`.

## Tools

`ente_apps`, `ente_status`, `ente_list_watches`, `ente_queue`, `ente_pending`, `ente_ensure_watch`, `ente_accounts`, `ente_export`, `ente_auth_decrypt`, `ente_locker_status`.

Config: see `config.example.toml`. Do not edit `watch-status.json` while that Ente desktop process is running. Do not merge desktop profiles.

## License

MCP Python code: MIT. The rest of this repository remains AGPL as upstream Ente.
