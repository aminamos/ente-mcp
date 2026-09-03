from __future__ import annotations

from pathlib import Path

import pytest

from ente_mcp.cli import main


def test_help_and_version() -> None:
    assert main([]) == 0
    assert main(["--version"]) == 0


def test_apps_without_official_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
default_client = "photos"
ente_cli = "ente-cli-not-installed-xyz"

[clients.photos]
app = "photos"
process = "ente"
profile = "ente"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ENTE_MCP_CONFIG", str(cfg))
    monkeypatch.setenv("ENTE_CLI", "ente-cli-not-installed-xyz")
    assert main(["apps"]) == 0
    assert main(["locker", "status"]) == 1
