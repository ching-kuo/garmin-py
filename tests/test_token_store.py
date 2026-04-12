"""Tests for token-store helpers and default-home migration."""
from __future__ import annotations

import stat
from pathlib import Path

from garmin_cli.token_store import DEFAULT_GARMIN_HOME, migrate_legacy_default_tokenstore, tokenstore_path


def test_migrate_legacy_default_tokenstore_copies_old_default(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    legacy_dir = tmp_path / ".garth"
    legacy_dir.mkdir(mode=0o700)
    legacy_token = legacy_dir / "garmin_tokens.json"
    legacy_token.write_text('{"di_token":"abc"}')

    migrate_legacy_default_tokenstore(DEFAULT_GARMIN_HOME)

    new_token = Path(tokenstore_path(DEFAULT_GARMIN_HOME))
    assert new_token.read_text() == '{"di_token":"abc"}'
    assert stat.S_IMODE(new_token.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(new_token.stat().st_mode) == 0o600


def test_migrate_legacy_default_tokenstore_preserves_existing_new_default(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HOME", str(tmp_path))

    legacy_dir = tmp_path / ".garth"
    legacy_dir.mkdir(mode=0o700)
    (legacy_dir / "garmin_tokens.json").write_text('{"di_token":"old"}')

    new_token = Path(tokenstore_path(DEFAULT_GARMIN_HOME))
    new_token.parent.mkdir(mode=0o700)
    new_token.write_text('{"di_token":"new"}')

    migrate_legacy_default_tokenstore(DEFAULT_GARMIN_HOME)

    assert new_token.read_text() == '{"di_token":"new"}'
