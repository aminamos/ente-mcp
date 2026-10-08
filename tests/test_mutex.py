from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ente_mcp import mutex


@pytest.fixture()
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(mutex, "state_dir", lambda: tmp_path)
    return tmp_path


def test_stale_marker_swept(state: Path) -> None:
    # Pid 999999999 is implausible; marker with only dead pids is swept.
    mutex.write_marker(999999999, 999999998)
    assert mutex.export_active() is False
    assert not (state / "export-active").exists()


def test_live_marker_blocks(state: Path) -> None:
    mutex.write_marker(os.getpid(), 0)
    assert mutex.export_active() is True


def test_corrupt_marker_swept(state: Path) -> None:
    (state / "export-active").write_text("not json", encoding="utf-8")
    assert mutex.export_active() is False


def test_single_export_at_a_time(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mutex, "stop_desktops", lambda: ["etne.exe"])
    with mutex.export_session() as session:
        assert session["killed_desktops"] == ["etne.exe"]
        assert mutex.export_active() is True
        with pytest.raises(mutex.ExportBusy):
            with mutex.export_session():
                pass
    assert mutex.export_active() is False
    assert not (state / "export-active").exists()


def test_export_session_kills_uploaders(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(mutex, "stop_desktops", lambda: calls.append(["etne.exe"]))
    with mutex.export_session():
        pass
    assert calls == [["etne.exe"]]
