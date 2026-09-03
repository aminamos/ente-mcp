from __future__ import annotations

from ente_mcp.official import parse_accounts


def test_parse_accounts_photos_auth_locker() -> None:
    text = """
Configured accounts: 3
====================================
Email:     you@example.com
ID:        11
App:      photos
ExportDir: /data/photos
====================================
====================================
Email:     you@example.com
ID:        11
App:      auth
ExportDir: /data/auth
====================================
====================================
Email:     you@example.com
ID:        11
App:      locker
ExportDir:
====================================
"""
    accounts = parse_accounts(text)
    assert [a.app for a in accounts] == ["photos", "auth", "locker"]
    assert accounts[0].email == "you@example.com"
    assert accounts[1].export_dir == "/data/auth"
    assert accounts[2].export_dir == ""
