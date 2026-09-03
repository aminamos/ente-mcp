from __future__ import annotations

from pathlib import Path

import pytest

from ente_mcp.config import Client
from ente_mcp.photos import (
    ensure_watch,
    is_media,
    pending_files,
    queue_files,
    safe_album,
    watch_summary,
)


def test_safe_album_rejects_paths() -> None:
    assert safe_album(" Inbox ") == "Inbox"
    with pytest.raises(ValueError):
        safe_album("a/b")
    with pytest.raises(ValueError):
        safe_album("..")


def test_is_media_matches_desktop_ignore_list(tmp_path: Path) -> None:
    assert is_media(tmp_path / "shot.jpg")
    assert is_media(tmp_path / "clip.mp4")
    assert not is_media(tmp_path / ".hidden.jpg")
    assert not is_media(tmp_path / "notes.txt")
    assert not is_media(tmp_path / "archive.zip")
    assert not is_media(tmp_path / "meta.xmp")


def test_queue_and_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ente_mcp.photos.process_running", lambda _image: False)
    user_data = tmp_path / "profile"
    queue = tmp_path / "queue"
    src = tmp_path / "shot.jpg"
    src.write_bytes(b"jpeg")
    skipped = tmp_path / "notes.txt"
    skipped.write_text("nope", encoding="utf-8")
    client = Client(
        name="photos",
        app="photos",
        process="ente",
        profile="ente",
        queue=queue,
        user_data=user_data,
    )
    result = queue_files(client, [str(src), str(skipped)], album="Inbox")
    assert result["registered"] is True
    assert result["queued"][0]["method"] in {"hardlink", "copy"}
    assert result["skipped"][0]["reason"] == "ignored by Ente"
    dest = queue / "Inbox" / "shot.jpg"
    assert dest.is_file()
    pending = pending_files(client)
    assert pending["pending"] == 1
    summary = watch_summary(client)
    assert summary["watches"][0]["registered"] is True
    assert summary["watches"][0]["pending"] == 1


def test_ensure_watch_refuses_when_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ente_mcp.photos.process_running", lambda _image: True)
    client = Client(
        name="photos",
        app="photos",
        process="ente",
        profile="ente",
        queue=tmp_path / "queue",
        user_data=tmp_path / "profile",
    )
    result = ensure_watch(client)
    assert result["ok"] is False
    assert "running" in result["reason"]
    assert not (tmp_path / "profile" / "watch-status.json").exists()


def test_watch_folders_reject_auth_client() -> None:
    client = Client(name="auth", app="auth")
    with pytest.raises(ValueError, match="Photos desktop only"):
        watch_summary(client)
