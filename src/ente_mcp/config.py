from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ente_mcp.paths import electron_user_data, package_dir, posix, user_config_dir

APPS = ("photos", "auth", "locker")


@dataclass(frozen=True)
class Client:
    name: str
    app: str
    process: str | None = None
    profile: str | None = None
    queue: Path | None = None
    user_data: Path | None = None

    def data_dir(self) -> Path | None:
        if self.user_data is not None:
            return self.user_data
        if self.profile:
            return electron_user_data(self.profile)
        return None

    def watch_store(self) -> Path | None:
        data = self.data_dir()
        if data is None:
            return None
        return data / "watch-status.json"


@dataclass(frozen=True)
class Config:
    default_client: str
    ente_cli: str
    clients: dict[str, Client]
    config_path: Path | None
    museum_endpoint: str = "https://api.ente.com"
    museum_email: str = ""

def _default_clients() -> dict[str, Client]:
    return {
        "photos": Client(name="photos", app="photos", process="ente", profile="ente"),
        "auth": Client(name="auth", app="auth"),
        "locker": Client(name="locker", app="locker"),
    }


def _parse_client(name: str, raw: dict) -> Client:
    app = str(raw.get("app") or "photos").strip().lower()
    if app not in APPS:
        raise ValueError(f"client {name!r} has invalid app {app!r}; use {', '.join(APPS)}")
    queue = raw.get("queue")
    user_data = raw.get("user_data")
    return Client(
        name=name,
        app=app,
        process=(str(raw["process"]).strip() if raw.get("process") else None),
        profile=(str(raw["profile"]).strip() if raw.get("profile") else None),
        queue=Path(str(queue)).expanduser() if queue else None,
        user_data=Path(str(user_data)).expanduser() if user_data else None,
    )


def config_search_paths() -> list[Path]:
    cwd = Path.cwd()
    root = package_dir()
    return [
        cwd / "config.local.toml",
        cwd / "config.toml",
        root / "config.local.toml",
        root / "config.toml",
        user_config_dir() / "config.toml",
    ]

def load_toml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    data = tomllib.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a TOML table")
    return data


def load_config() -> Config:
    clients = _default_clients()
    default_client = "photos"
    ente_cli = os.environ.get("ENTE_CLI", "ente")
    museum_endpoint = os.environ.get("ENTE_MCP_MUSEUM", "") or "https://api.ente.com"
    museum_email = ""
    used: Path | None = None
    env_path = os.environ.get("ENTE_MCP_CONFIG")
    candidates = [Path(env_path).expanduser()] if env_path else config_search_paths()
    for path in candidates:
        if not path.is_file():
            continue
        used = path
        data = load_toml(path)
        default_client = str(data.get("default_client") or default_client)
        if data.get("ente_cli"):
            ente_cli = str(data["ente_cli"])
        raw_museum = data.get("museum") or {}
        if not isinstance(raw_museum, dict):
            raise ValueError(f"{path}: museum must be a table")
        if raw_museum.get("endpoint"):
            museum_endpoint = str(raw_museum["endpoint"]).rstrip("/") or museum_endpoint
        if raw_museum.get("email"):
            museum_email = str(raw_museum["email"]).strip()
        raw_clients = data.get("clients") or {}
        if not isinstance(raw_clients, dict):
            raise ValueError(f"{path}: clients must be a table")
        for name, raw in raw_clients.items():
            if not isinstance(raw, dict):
                raise ValueError(f"{path}: clients.{name} must be a table")
            clients[str(name)] = _parse_client(str(name), raw)
        break
    env_cli = os.environ.get("ENTE_CLI")
    if env_cli:
        ente_cli = env_cli
    env_default = os.environ.get("ENTE_MCP_CLIENT")
    if env_default:
        default_client = env_default
    if default_client not in clients:
        default_client = next(iter(clients))
    return Config(
        default_client=default_client,
        ente_cli=ente_cli,
        clients=clients,
        config_path=used,
        museum_endpoint=museum_endpoint,
        museum_email=museum_email,
    )


def get_client(config: Config, name: str | None) -> Client:
    key = (name or config.default_client).strip().lower()
    if key not in config.clients:
        known = ", ".join(sorted(config.clients))
        raise ValueError(f"unknown client {name!r}; configured: {known}")
    return config.clients[key]


def client_summary(client: Client) -> dict:
    queue = posix(client.queue) if client.queue else None
    data = client.data_dir()
    return {
        "name": client.name,
        "app": client.app,
        "process": client.process,
        "profile": client.profile,
        "queue": queue,
        "userData": posix(data) if data else None,
        "watchStore": posix(client.watch_store()) if client.watch_store() else None,
    }
