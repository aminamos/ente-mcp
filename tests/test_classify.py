from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "classify_to_ente", ROOT / "scripts" / "classify_to_ente.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("decision", "score", "album", "expected"),
    [
        ("sensitive", 0.90, "Inbox", ".hidden"),
        ("likely_sensitive", 0.70, "Inbox", ".hidden"),
        ("uncertain", 0.50, "Friends", ".hidden"),
        ("likely_safe", 0.55, "Friends", ".hidden"),
        ("likely_safe", 0.54, "Friends", "Friends"),
        ("safe", 0.10, "Friends", "Friends"),
        ("safe", 0.99, "Inbox", ".hidden"),  # score override wins over safe decision
        ("unknown", 0.40, "Inbox", "Inbox"),
    ],
)
def test_classify_target_ensemble_routing(decision: str, score: float, album: str, expected: str) -> None:
    assert MODULE.classify_target_ensemble(decision, score, album) == expected


def test_classify_target_ensemble_threshold_override() -> None:
    assert MODULE.classify_target_ensemble("safe", 0.50, "Inbox", threshold=0.50) == ".hidden"
    assert MODULE.classify_target_ensemble("safe", 0.49, "Inbox", threshold=0.50) == "Inbox"


def test_image_suffix_set() -> None:
    assert ".jpg" in MODULE.IMAGE_SUFFIXES
    assert ".mp4" not in MODULE.IMAGE_SUFFIXES


def test_cli_cmd_uses_python_module_not_server_binary() -> None:
    # ente-mcp.exe is the MCP server entry (ente_mcp.server); invoking it with CLI
    # args silently exits 0 and queues nothing. The CLI must run via python -m.
    cmd = MODULE.cli_cmd(["photos", "queue", "x.jpg", "--album", "Inbox"])
    assert cmd[0].endswith("python.exe")
    assert cmd[-7:] == ["-m", "ente_mcp.cli", "photos", "queue", "x.jpg", "--album", "Inbox"]


def test_queue_fails_on_non_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    # A server binary that swallows CLI args returns empty stdout with code 0;
    # queue() must report failure instead of a false success.
    import subprocess

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=(), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = MODULE.queue(Path("x.jpg"), "Inbox")
    assert result.get("ok") is False