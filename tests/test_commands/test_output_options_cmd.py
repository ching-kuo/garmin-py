"""--json/--format after the subcommand, and JSON-error detection."""
from __future__ import annotations

import json
import sys
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import _requested_format, cli
from garmin_cli.commands._options import stdin_is_tty
from garmin_cli.doctor import CheckResult
from garmin_cli.exceptions import GarminCliError


def _patch_sleep(mocker: Any) -> None:
    mocker.patch("garmin_cli.commands._options.ensure_authenticated")
    mocker.patch("garmin_cli.commands.health.get_sleep", return_value={})
    mocker.patch(
        "garmin_cli.commands.health.serialize_sleep",
        return_value=[{"date": "2026-03-11", "score": 80}],
    )


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["health", "sleep", "--days", "1", "--json"], "json"),
        (["health", "sleep", "--format", "json", "--days", "1"], "json"),
        (["--json", "health", "sleep", "--days", "1", "--format", "csv"], "csv"),
        (["--format", "csv", "health", "sleep", "--days", "1", "--json"], "json"),
        (["health", "sleep", "--format", "csv", "--json", "--days", "1"], "json"),
        (["health", "sleep", "--json", "--format", "csv", "--days", "1"], "json"),
    ],
)
def test_leaf_output_options_override_global(
    mocker: Any, args: list[str], expected: str
) -> None:
    _patch_sleep(mocker)

    result = CliRunner(mix_stderr=False).invoke(cli, args)

    assert result.exit_code == 0, result.stderr
    if expected == "json":
        assert json.loads(result.stdout)["command"] == "health sleep"
    else:
        assert result.stdout.splitlines()[1].startswith("2026-03-11,")


def test_leaf_json_error_uses_envelope(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.commands.activities.ensure_authenticated",
        side_effect=GarminCliError(error="no session", error_code="AUTH_MISSING"),
    )

    result = CliRunner(mix_stderr=False).invoke(cli, ["activity", "list", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "AUTH_MISSING"


def test_option_value_equal_to_json_flag_is_not_the_flag(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.commands.activities.ensure_authenticated",
        side_effect=GarminCliError(error="no session", error_code="AUTH_MISSING"),
    )

    result = CliRunner(mix_stderr=False).invoke(
        cli, ["activity", "list", "--search", "--json"]
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "no session" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["activity", "list", "--search", "--json", "--days", "0"],
        ["--json", "health", "sleep", "--format", "table", "--days", "0"],
        ["--json", "workout", "calendar", "--format", "table", "--days", "1", "--ahead", "1"],
    ],
)
def test_usage_error_after_parsing_uses_parsed_format(mocker: Any, args: list[str]) -> None:
    mocker.patch("garmin_cli.commands._options.ensure_authenticated")
    mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
    mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")

    result = CliRunner(mix_stderr=False).invoke(cli, args)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.strip()


def test_error_envelope_names_resolved_command(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.commands.login.resume_and_probe",
        side_effect=GarminCliError(error="Garmin is down", error_code="SERVER_ERROR"),
    )

    result = CliRunner(mix_stderr=False).invoke(
        cli, ["login", "--email", "a@example.com", "status", "--json"]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["command"] == "login status"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--format", "json", "--format", "table"], "table"),
        (["--format", "table", "--format=JSON"], "json"),
        (["--format", "csv", "--json"], "json"),
        (["--format", "invalid"], None),
        (["--format=bad"], None),
        (["--", "--json"], None),
    ],
)
def test_requested_format_scan(args: list[str], expected: str | None) -> None:
    assert _requested_format(args) == expected


def test_requested_format_skips_global_option_values() -> None:
    assert _requested_format(["--garmin-home", "--json"], skip_global_values=True) is None


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--json", "health", "sleep", "--format", "invalid"], "json"),
        (["--garmin-home", "--json", "health", "sleep", "--bad-flag"], "plain"),
        (["--json", "health", "sleep", "--bad-flag"], "json"),
        (["health", "sleep", "--json", "--bad-flag"], "json"),
        (["--json", "health", "sleep", "--format", "table", "--bad-flag"], "plain"),
        (["--json", "no-such-command"], "json"),
    ],
)
def test_parse_time_errors_resolve_format(args: list[str], expected: str) -> None:
    result = CliRunner(mix_stderr=False).invoke(cli, args)

    assert result.exit_code == 1
    if expected == "json":
        assert json.loads(result.stdout)["error_code"] == "INVALID_INPUT"
    else:
        assert result.stdout == ""
        assert result.stderr.strip()


def test_nested_parse_error_deepest_level_wins_and_is_labeled(mocker: Any) -> None:
    result = CliRunner(mix_stderr=False).invoke(
        cli, ["login", "--json", "status", "--format", "table", "--bogus"]
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "--bogus" in result.stderr

    result = CliRunner(mix_stderr=False).invoke(cli, ["login", "--json", "status", "--bogus"])
    assert json.loads(result.stdout)["command"] == "login status"


def test_command_label_ignores_program_name(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.commands.activities.ensure_authenticated",
        side_effect=GarminCliError(error="no session", error_code="AUTH_MISSING"),
    )

    result = CliRunner(mix_stderr=False).invoke(
        cli, ["activity", "list", "--json"], prog_name="python -m garmin_cli"
    )

    assert json.loads(result.stdout)["command"] == "activity list"


def test_reused_obj_does_not_leak_previous_state(mocker: Any) -> None:
    obj: dict[str, Any] = {"parsed_command": "stale", "config": None}

    result = CliRunner(mix_stderr=False).invoke(cli, ["--json", "no-such-command"], obj=obj)

    assert json.loads(result.stdout)["command"] == "garmin-cli"


def test_missing_stdin_is_not_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", None)

    assert stdin_is_tty() is False


@pytest.mark.parametrize(
    "args",
    [
        ["workout", "delete", "abc"],
        ["workout", "unschedule", "0"],
        ["activity", "delete", "1.5"],
    ],
)
def test_ids_are_validated_before_prompting(mocker: Any, args: list[str]) -> None:
    mocker.patch("garmin_cli.commands._options.stdin_is_tty", return_value=True)

    result = CliRunner(mix_stderr=False).invoke(cli, args, input="y\n")

    assert result.exit_code == 1
    assert "positive integer" in result.stderr
    assert "?" not in result.stderr  # never prompted


def test_interrupt_exits_130(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.commands.activities.ensure_authenticated", side_effect=KeyboardInterrupt
    )

    result = CliRunner(mix_stderr=False).invoke(cli, ["activity", "list", "--json"])

    assert result.exit_code == 130
    envelope = json.loads(result.stdout)
    assert envelope["error_code"] == "INTERRUPTED"
    assert envelope["error"] == "Interrupted."


def test_doctor_supports_csv(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.commands.doctor.run_checks",
        return_value=[CheckResult("python_version", True, "ok")],
    )

    result = CliRunner(mix_stderr=False).invoke(cli, ["doctor", "--format", "csv"])

    assert result.exit_code == 0
    assert result.stdout.splitlines()[0] == "name,ok,detail,error_code,recovery_hint"


def test_root_help_has_description_and_examples() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert "Examples:" in result.output
    assert "garmin-cli health sleep --days 7" in result.output


def test_workout_create_help_shows_file_optional() -> None:
    result = CliRunner().invoke(cli, ["workout", "create", "--help"])

    assert "[FILE]" in result.output
    assert "--dry-run" in result.output
