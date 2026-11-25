"""Tests for token-store helpers."""
from __future__ import annotations

import os
import stat

import pytest

from garmin_cli.exceptions import GarminCliError
from garmin_cli.token_store import (
    DEFAULT_GARMIN_HOME,
    ensure_secure_directory,
    tokenstore_path,
    validate_garmin_home,
)


def test_default_home_never_copies_a_legacy_garth_token(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_dir = tmp_path / ".garth"
    legacy_dir.mkdir(mode=0o700)
    (legacy_dir / "garmin_tokens.json").write_text('{"di_token":"abc"}')

    home = ensure_secure_directory(DEFAULT_GARMIN_HOME, create=True)

    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert not os.path.lexists(tokenstore_path(DEFAULT_GARMIN_HOME))


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
