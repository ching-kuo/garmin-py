"""Unit and CLI tests for diagnostics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from garmin_cli.auth import SessionProbeResult
from garmin_cli.cli import cli
from garmin_cli.config import CliConfig
from garmin_cli.doctor import check_session, check_write_surface, run_checks
from garmin_cli.mcp_cli import _MCP_BEARER_ENV


def _secure_home(path: Path, *, token: bool = True) -> None:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    if token:
        (path / "garmin_tokens.json").write_text("{}")


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
    monkeypatch.delenv(_MCP_BEARER_ENV, raising=False)
    without_token = check_write_surface(CliConfig())
    monkeypatch.setenv(_MCP_BEARER_ENV, "x")
    with_token = check_write_surface(CliConfig())

    assert without_token.ok is True
    assert "Bearer token configured: false" in without_token.detail
    assert with_token.ok is True
    assert "Bearer token configured: true" in with_token.detail


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
