"""CLI tests for `workout send` (Garmin write: mocked, never live)."""
from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli
from garmin_cli.endpoints.workouts import send_workout_to_device as endpoint_send
from garmin_cli.exceptions import GarminCliError
from tests.helpers import EDGE, FENIX, HRM, workout


def _patch(mocker: Any, devices: list[dict[str, Any]], sport: str = "running") -> tuple[Any, Any]:
    auth = mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
    mocker.patch("garmin_cli.services.workouts.get_workout", return_value=workout(sport))
    mocker.patch("garmin_cli.services.workouts.get_devices", return_value=devices)
    send = mocker.patch("garmin_cli.commands.workouts.send_workout_to_device", return_value=None)
    return auth, send


def _invoke(args: list[str], stdin: str | None = None) -> Any:
    return CliRunner(mix_stderr=False).invoke(cli, args, input=stdin)


def test_auto_picks_the_device_that_takes_the_sport(mocker: Any) -> None:
    _, send = _patch(mocker, [FENIX, EDGE, HRM])
    result = _invoke(["--json", "workout", "send", "123", "--yes"])
    assert result.exit_code == 0, result.output
    send.assert_called_once_with(123, "Tempo", 11)
    assert json.loads(result.stdout)["data"] == [{
        "workout_id": 123, "workout_name": "Tempo", "device_id": 11, "display_name": "fenix 8", "status": "sent",
    }]


def test_explicit_device_is_used(mocker: Any) -> None:
    _, send = _patch(mocker, [FENIX, EDGE], sport="cycling")
    result = _invoke(["workout", "send", "123", "--device", "22", "--yes"])
    assert result.exit_code == 0, result.output
    send.assert_called_once_with(123, "Tempo", 22)


def test_dry_run_resolves_without_sending_or_prompting(mocker: Any) -> None:
    _, send = _patch(mocker, [FENIX])
    result = _invoke(["--json", "workout", "send", "123", "--dry-run"])
    assert result.exit_code == 0, result.output
    send.assert_not_called()
    assert json.loads(result.stdout)["data"][0]["status"] == "dry_run"


def test_dry_run_fails_for_a_missing_workout(mocker: Any) -> None:
    _, send = _patch(mocker, [FENIX])
    mocker.patch(
        "garmin_cli.services.workouts.get_workout",
        side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
    )
    result = _invoke(["--json", "workout", "send", "999", "--dry-run"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "NOT_FOUND"
    send.assert_not_called()


@pytest.mark.parametrize(
    ("devices", "args", "message"),
    [
        ([FENIX, EDGE], ["--device", "22"], "Device 22 cannot receive running workouts"),
        ([FENIX, HRM], ["--device", "33"], "cannot receive workouts"),
    ],
)
def test_incapable_device_is_refused(
    mocker: Any, devices: list[dict[str, Any]], args: list[str], message: str
) -> None:
    _, send = _patch(mocker, devices)
    result = _invoke(["--json", "workout", "send", "123", *args, "--yes"])
    assert result.exit_code == 1
    error = json.loads(result.stdout)
    assert error["error_code"] == "INVALID_INPUT"
    assert message in error["error"]
    send.assert_not_called()


def test_interactive_prompt_names_the_workout_and_device_after_resolving(mocker: Any) -> None:
    mocker.patch("garmin_cli.commands._options.stdin_is_tty", return_value=True)
    auth, send = _patch(mocker, [FENIX])
    result = _invoke(["workout", "send", "123"], stdin="n\n")
    assert result.exit_code == 1
    assert "Send workout Tempo (123) to fenix 8 (11)?" in result.stderr
    auth.assert_called_once()
    send.assert_not_called()


def test_accepted_prompt_sends(mocker: Any) -> None:
    mocker.patch("garmin_cli.commands._options.stdin_is_tty", return_value=True)
    _, send = _patch(mocker, [FENIX])
    result = _invoke(["workout", "send", "123"], stdin="y\n")
    assert result.exit_code == 0, result.stderr
    send.assert_called_once_with(123, "Tempo", 11)


@pytest.mark.parametrize(
    ("name", "shown"), [("\x1b[2K\rEvil\n", "to [2KEvil (11)?"), (None, "to unnamed device (11)?")]
)
def test_prompt_prints_device_names_safely(mocker: Any, name: str | None, shown: str) -> None:
    mocker.patch("garmin_cli.commands._options.stdin_is_tty", return_value=True)
    _patch(mocker, [{**FENIX, "displayName": name}])
    result = _invoke(["workout", "send", "123"], stdin="n\n")
    assert shown in result.stderr
    assert "\x1b" not in result.stderr


@pytest.mark.parametrize(("json_flag", "tty"), [(["--json"], True), ([], False)])
def test_non_interactive_without_yes_fails_before_login(mocker: Any, json_flag: list[str], tty: bool) -> None:
    mocker.patch("garmin_cli.commands._options.stdin_is_tty", return_value=tty)
    auth, send = _patch(mocker, [FENIX])
    result = _invoke([*json_flag, "workout", "send", "123"])
    assert result.exit_code == 1
    assert "Confirmation required" in result.output + result.stderr
    auth.assert_not_called()
    send.assert_not_called()


def test_send_that_may_have_landed_says_so(mocker: Any) -> None:
    _patch(mocker, [FENIX])
    mocker.patch("garmin_cli.commands.workouts.send_workout_to_device", endpoint_send)
    garth = mocker.patch("garmin_cli.endpoints.workouts.garth")
    garth.send_workout_message.side_effect = TimeoutError("read timed out")
    result = _invoke(["--json", "workout", "send", "123", "--yes"])
    assert result.exit_code == 1
    error = json.loads(result.stdout)
    assert error["error_code"] == "NETWORK_ERROR"
    assert "may already be queued" in error["error"]
    garth.send_workout_message.assert_called_once()


@pytest.mark.parametrize("args", [["0"], ["123", "--device", "-1"]])
def test_invalid_ids_fail_before_login(mocker: Any, args: list[str]) -> None:
    auth, send = _patch(mocker, [FENIX])
    result = _invoke(["--json", "workout", "send", *args, "--yes"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "INVALID_INPUT"
    auth.assert_not_called()
    send.assert_not_called()
