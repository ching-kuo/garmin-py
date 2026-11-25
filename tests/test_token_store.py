"""Tests for token-store helpers and default-home migration."""
from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

import pytest

from garmin_cli.exceptions import GarminCliError
from garmin_cli.token_store import (
    DEFAULT_GARMIN_HOME,
    ensure_secure_directory,
    legacy_tokenstore_path,
    migrate_legacy_default_tokenstore,
    tokenstore_path,
    validate_garmin_home,
)


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


def test_migrate_creates_token_owner_only_without_chmod(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_dir = tmp_path / ".garth"
    legacy_dir.mkdir(mode=0o700)
    legacy_token = legacy_dir / "garmin_tokens.json"
    legacy_token.write_text('{"di_token":"abc"}')
    legacy_token.chmod(0o644)
    chmod_calls: list[object] = []
    monkeypatch.setattr("garmin_cli.token_store.os.chmod", lambda *a: chmod_calls.append(a))

    migrate_legacy_default_tokenstore(DEFAULT_GARMIN_HOME)

    new_token = Path(tokenstore_path(DEFAULT_GARMIN_HOME))
    assert stat.S_IMODE(new_token.stat().st_mode) == 0o600
    assert chmod_calls == []  # never world-readable, not even briefly
    assert [p.name for p in new_token.parent.iterdir()] == ["garmin_tokens.json"]


@pytest.mark.parametrize("link", ["dir", "file"])
def test_migrate_refuses_symlinked_legacy_source(monkeypatch, tmp_path, link):
    monkeypatch.setenv("HOME", str(tmp_path))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "garmin_tokens.json").write_text('{"di_token":"planted"}')
    if link == "dir":
        (tmp_path / ".garth").symlink_to(elsewhere)
    else:
        (tmp_path / ".garth").mkdir()
        (tmp_path / ".garth" / "garmin_tokens.json").symlink_to(elsewhere / "garmin_tokens.json")

    migrate_legacy_default_tokenstore(DEFAULT_GARMIN_HOME)

    assert not Path(tokenstore_path(DEFAULT_GARMIN_HOME)).exists()


def test_migrate_skips_non_regular_legacy_source(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".garth" / "garmin_tokens.json").mkdir(parents=True)

    migrate_legacy_default_tokenstore(DEFAULT_GARMIN_HOME)

    assert not os.path.lexists(tokenstore_path(DEFAULT_GARMIN_HOME))


def test_migrate_never_overwrites_a_token_that_appeared_meanwhile(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_dir = tmp_path / ".garth"
    legacy_dir.mkdir()
    (legacy_dir / "garmin_tokens.json").write_text('{"di_token":"old"}')
    new_token = Path(tokenstore_path(DEFAULT_GARMIN_HOME))
    real_link = os.link

    def _login_wins_race(src, dst):
        new_token.write_text('{"di_token":"fresh"}')
        real_link(src, dst)

    monkeypatch.setattr("garmin_cli.token_store.os.link", _login_wins_race)

    migrate_legacy_default_tokenstore(DEFAULT_GARMIN_HOME)

    assert new_token.read_text() == '{"di_token":"fresh"}'
    assert [p.name for p in new_token.parent.iterdir()] == ["garmin_tokens.json"]


def test_migrate_does_not_hang_on_a_fifo_legacy_token(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".garth").mkdir()
    os.mkfifo(tmp_path / ".garth" / "garmin_tokens.json")

    migrate_legacy_default_tokenstore(DEFAULT_GARMIN_HOME)  # returns instead of blocking

    assert not os.path.lexists(tokenstore_path(DEFAULT_GARMIN_HOME))


def test_legacy_home_that_is_a_file_means_no_legacy_token(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".garth").write_text("not a directory")

    assert legacy_tokenstore_path() is None
    migrate_legacy_default_tokenstore(DEFAULT_GARMIN_HOME)
    assert not os.path.lexists(tokenstore_path(DEFAULT_GARMIN_HOME))


def test_migrate_falls_back_when_hard_links_are_unsupported(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".garth").mkdir()
    (tmp_path / ".garth" / "garmin_tokens.json").write_text('{"di_token":"abc"}')

    def _no_hard_links(src, dst):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr("garmin_cli.token_store.os.link", _no_hard_links)

    migrate_legacy_default_tokenstore(DEFAULT_GARMIN_HOME)

    new_token = Path(tokenstore_path(DEFAULT_GARMIN_HOME))
    assert new_token.read_text() == '{"di_token":"abc"}'
    assert stat.S_IMODE(new_token.stat().st_mode) == 0o600
    assert [p.name for p in new_token.parent.iterdir()] == ["garmin_tokens.json"]


def test_failed_migration_never_blocks_securing_the_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    def _broken(_path):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr("garmin_cli.token_store.migrate_legacy_default_tokenstore", _broken)

    home = ensure_secure_directory(DEFAULT_GARMIN_HOME, create=True)

    assert stat.S_IMODE(home.stat().st_mode) == 0o700


@pytest.mark.parametrize("name", ["tokens.json", "Tokens.JSON"])
def test_json_file_path_is_rejected_as_garmin_home(tmp_path, name):
    json_home = str(tmp_path / name)

    assert tokenstore_path(json_home) == tmp_path / name / "garmin_tokens.json"
    with pytest.raises(GarminCliError, match="must be a directory") as exc_info:
        ensure_secure_directory(json_home, create=True)
    assert exc_info.value.error_code == "INVALID_INPUT"
    assert not (tmp_path / name).exists()


def test_validate_rejects_symlinked_parent_component(tmp_path):
    real = tmp_path / "real"
    (real / "garmin").mkdir(parents=True)
    (tmp_path / "link").symlink_to(real)

    with pytest.raises(GarminCliError, match="symlink") as exc_info:
        validate_garmin_home(str(tmp_path / "link" / "garmin") + "/")
    assert exc_info.value.error_code == "AUTH_FAILED"


def test_validate_rejects_existing_file_home(tmp_path):
    (tmp_path / "home").write_text("")

    with pytest.raises(GarminCliError) as exc_info:
        validate_garmin_home(str(tmp_path / "home"))
    assert exc_info.value.error_code == "INVALID_INPUT"
