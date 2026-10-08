from __future__ import annotations

from pathlib import Path

import pytest

from ente_mcp.config import load_config


def test_env_config_does_not_fall_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
default_client = "museum"

[clients.museum]
app = "photos"
process = "etne"
profile = "etne"
queue = "E:/tmp/ente-queue"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ENTE_MCP_CONFIG", str(cfg))
    monkeypatch.delenv("ENTE_MCP_CLIENT", raising=False)
    loaded = load_config()
    assert loaded.default_client == "museum"
    assert loaded.clients["museum"].process == "etne"
    assert loaded.config_path == cfg


def test_missing_env_config_uses_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENTE_MCP_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.delenv("ENTE_MCP_CLIENT", raising=False)
    loaded = load_config()
    assert loaded.default_client == "photos"
    assert set(loaded.clients) >= {"photos", "auth", "locker"}
