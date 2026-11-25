"""Unit and CLI tests for diagnostics."""
from __future__ import annotations

import json
import sys
from collections import namedtuple
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.auth import SessionProbeResult
from garmin_cli.bearer_token import BEARER_ENV, BEARER_TOKEN_HINT, MIN_BEARER_TOKEN_LENGTH
from garmin_cli.cli import cli
from garmin_cli.config import CliConfig
from garmin_cli.doctor import (
    check_config,
    check_python_version,
    check_session,
    check_token_store,
    check_write_surface,
    run_checks,
)


def _secure_home(path: Path, *, token: bool = True) -> None:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    if token:
        (path / "garmin_tokens.json").write_text("{}")
        (path / "garmin_tokens.json").chmod(0o600)


def test_fast_checks_skip_network(tmp_path: Path, mocker: Any) -> None:
    home = tmp_path / "garmin"
    _secure_home(home)
    probe = mocker.patch("garmin_cli.doctor.probe_session_status")

    results = run_checks(CliConfig(garth_home=str(home)), fast=True)

    probe.assert_not_called()
    session = next(result for result in results if result.name == "session")
    assert session.ok is True
    assert "Skipped" in session.detail


def test_missing_token_store_has_auth_missing_hint(tmp_path: Path) -> None:
    home = tmp_path / "garmin"
    _secure_home(home, token=False)

    results = run_checks(CliConfig(garth_home=str(home)), fast=True)
    token = next(result for result in results if result.name == "token_store")

    assert token.ok is False
    assert token.error_code == "AUTH_MISSING"
    assert "garmin-cli login" in (token.recovery_hint or "")


def test_legacy_token_layout_is_reported(tmp_path: Path) -> None:
    home = tmp_path / "garmin"
    _secure_home(home, token=False)
    (home / "oauth1_token.json").write_text("{}")

    results = run_checks(CliConfig(garth_home=str(home)), fast=True)
    token = next(result for result in results if result.name == "token_store")

    assert token.ok is False
    assert "Legacy" in token.detail


def test_token_file_with_loose_mode_is_reported(tmp_path: Path) -> None:
    home = tmp_path / "garmin"
    _secure_home(home)
    (home / "garmin_tokens.json").chmod(0o644)

    token = check_token_store(CliConfig(garth_home=str(home)))

    assert token.ok is False
    assert token.error_code == "AUTH_FAILED"
    assert "0644" in token.detail
    assert token.recovery_hint == "Restrict garmin_tokens.json to owner read/write (mode 600)."


def test_symlinked_token_file_is_reported(tmp_path: Path) -> None:
    home = tmp_path / "garmin"
    _secure_home(home, token=False)
    real = tmp_path / "real.json"
    real.write_text("{}")
    real.chmod(0o600)
    (home / "garmin_tokens.json").symlink_to(real)

    token = check_token_store(CliConfig(garth_home=str(home)))

    assert token.ok is False
    assert token.error_code == "AUTH_FAILED"
    assert "symlink" in token.detail


def test_dangling_token_symlink_is_reported_as_symlink(tmp_path: Path) -> None:
    home = tmp_path / "garmin"
    _secure_home(home, token=False)
    (home / "garmin_tokens.json").symlink_to(tmp_path / "missing.json")

    token = check_token_store(CliConfig(garth_home=str(home)))

    assert token.error_code == "AUTH_FAILED"
    assert "symlink" in token.detail


def test_non_regular_token_file_is_reported(tmp_path: Path) -> None:
    home = tmp_path / "garmin"
    _secure_home(home, token=False)
    (home / "garmin_tokens.json").mkdir()

    token = check_token_store(CliConfig(garth_home=str(home)))

    assert token.error_code == "AUTH_FAILED"
    assert "regular file" in token.detail


def test_uninspectable_token_store_is_a_failure_not_internal_error(
    tmp_path: Path, mocker: Any
) -> None:
    home = tmp_path / "garmin"
    _secure_home(home)
    mocker.patch.object(Path, "lstat", side_effect=PermissionError("denied"))

    token = check_token_store(CliConfig(garth_home=str(home)))

    assert token.ok is False
    assert token.error_code == "AUTH_FAILED"


def test_json_garmin_home_is_invalid_input(tmp_path: Path) -> None:
    config = check_config(CliConfig(garth_home=str(tmp_path / "tokens.json")))

    assert config.error_code == "INVALID_INPUT"
    assert "must be a directory" in config.detail


def test_symlinked_home_component_is_named_in_config_failure(tmp_path: Path) -> None:
    (tmp_path / "real" / "garmin").mkdir(parents=True)
    (tmp_path / "link").symlink_to(tmp_path / "real")

    config = check_config(CliConfig(garth_home=str(tmp_path / "link" / "garmin")))

    assert config.error_code == "AUTH_FAILED"
    assert str(tmp_path / "link") in config.detail


def test_failed_session_probe_is_captured(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.doctor.probe_session_status",
        return_value=SessionProbeResult(
            authenticated=False,
            garmin_home="~/.garminconnect",
            latency_ms=12.5,
            error_code="AUTH_FAILED",
            detail="The saved Garmin session was rejected.",
        ),
    )

    result = check_session(CliConfig())

    assert result.ok is False
    assert result.error_code == "AUTH_FAILED"
    assert "12.5 ms" in result.detail


def test_write_surface_reports_bearer_token_state(monkeypatch: Any) -> None:
    monkeypatch.delenv(BEARER_ENV, raising=False)
    without_token = check_write_surface(CliConfig())
    monkeypatch.setenv(BEARER_ENV, "x" * MIN_BEARER_TOKEN_LENGTH)
    with_token = check_write_surface(CliConfig())

    assert without_token.ok is True
    assert "Bearer token configured: false" in without_token.detail
    assert with_token.ok is True
    assert "Bearer token configured: true" in with_token.detail


def test_write_surface_flags_short_bearer_token(monkeypatch: Any) -> None:
    monkeypatch.setenv(BEARER_ENV, "x" * (MIN_BEARER_TOKEN_LENGTH - 1))
    short = check_write_surface(CliConfig())

    assert short.ok is False
    assert f"at least {MIN_BEARER_TOKEN_LENGTH}" in short.detail
    assert BEARER_TOKEN_HINT in short.detail


@pytest.mark.parametrize(
    "token", ["", "  \t ", "ä" * MIN_BEARER_TOKEN_LENGTH, "a b" * MIN_BEARER_TOKEN_LENGTH]
)
def test_write_surface_flags_blank_or_invalid_bearer_token(
    monkeypatch: Any, token: str
) -> None:
    monkeypatch.setenv(BEARER_ENV, token)

    assert check_write_surface(CliConfig()).ok is False


_VersionInfo = namedtuple("_VersionInfo", "major minor micro releaselevel serial")


@pytest.mark.parametrize(("minor", "ok"), [(11, False), (12, True)])
def test_python_version_minimum_is_3_12(minor: int, ok: bool, mocker: Any) -> None:
    mocker.patch.object(sys, "version_info", _VersionInfo(3, minor, 0, "final", 0))

    result = check_python_version(CliConfig())

    assert result.ok is ok
    if not ok:
        assert "Python 3.12 or newer is required" in result.detail


def test_doctor_cli_healthy_fast_path_exits_zero(tmp_path: Path) -> None:
    home = tmp_path / "garmin"
    _secure_home(home)

    result = CliRunner().invoke(
        cli,
        ["--garmin-home", str(home), "doctor", "--fast", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert all(row["ok"] for row in payload["data"])


def test_doctor_cli_missing_token_exits_one(tmp_path: Path) -> None:
    home = tmp_path / "garmin"
    _secure_home(home, token=False)

    result = CliRunner().invoke(
        cli,
        ["--garmin-home", str(home), "doctor", "--fast", "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    token = next(row for row in payload["data"] if row["name"] == "token_store")
    assert token["error_code"] == "AUTH_MISSING"
