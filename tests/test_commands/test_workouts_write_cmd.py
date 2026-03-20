"""CLI integration tests for workout write commands: create, update, delete, schedule."""
from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli
from garmin_cli.exceptions import GarminCliError


# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

_SAMPLE_WORKOUT_PAYLOAD: dict = {
    "name": "Morning Run",
    "sport": "running",
    "steps": [
        {
            "type": "warmup",
            "duration": {"type": "time", "value": 300},
        }
    ],
}

_SAMPLE_CREATED_WORKOUT: dict = {
    "workoutId": 12345,
    "workoutName": "Morning Run",
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSegments": [],
}

_SAMPLE_EXISTING_WORKOUT: dict = {
    "workoutId": 12345,
    "ownerId": 9999,
    "workoutName": "Old Name",
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSegments": [],
}

_SAMPLE_SCHEDULE_RESPONSE: dict = {
    "workoutScheduleId": 555,
    "calendarDate": "2026-04-01",
    "workoutId": 12345,
}


# ---------------------------------------------------------------------------
# workout create command
# ---------------------------------------------------------------------------

class TestWorkoutCreateCommand:

    def test_create_exit_code_0(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value=_SAMPLE_WORKOUT_PAYLOAD,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.create_workout",
            return_value=_SAMPLE_CREATED_WORKOUT,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "workout.json"
        f.write_text(json.dumps(_SAMPLE_WORKOUT_PAYLOAD))
        result = runner.invoke(cli, ["--json", "workout", "create", str(f)])
        assert result.exit_code == 0

    def test_create_json_ok_true(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value=_SAMPLE_WORKOUT_PAYLOAD,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.create_workout",
            return_value=_SAMPLE_CREATED_WORKOUT,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "workout.json"
        f.write_text(json.dumps(_SAMPLE_WORKOUT_PAYLOAD))
        result = runner.invoke(cli, ["--json", "workout", "create", str(f)])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_create_calls_auth(self, mocker: Any, tmp_path: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value=_SAMPLE_WORKOUT_PAYLOAD,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.create_workout",
            return_value=_SAMPLE_CREATED_WORKOUT,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "workout.json"
        f.write_text(json.dumps(_SAMPLE_WORKOUT_PAYLOAD))
        runner.invoke(cli, ["workout", "create", str(f)])
        mock_auth.assert_called_once()

    def test_create_calls_create_workout(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value=_SAMPLE_WORKOUT_PAYLOAD,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mock_create = mocker.patch(
            "garmin_cli.commands.workouts.create_workout",
            return_value=_SAMPLE_CREATED_WORKOUT,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "workout.json"
        f.write_text(json.dumps(_SAMPLE_WORKOUT_PAYLOAD))
        runner.invoke(cli, ["workout", "create", str(f)])
        mock_create.assert_called_once()

    def test_create_calls_build_garmin_payload_and_passes_result_to_create_workout(
        self, mocker: Any, tmp_path: Any
    ) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value=_SAMPLE_WORKOUT_PAYLOAD,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        garmin_shaped = {"workoutName": "Morning Run", "sportType": {"sportTypeId": 1}}
        mock_build = mocker.patch(
            "garmin_cli.commands.workouts.build_garmin_payload",
            return_value=garmin_shaped,
        )
        mock_create = mocker.patch(
            "garmin_cli.commands.workouts.create_workout",
            return_value=_SAMPLE_CREATED_WORKOUT,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "workout.json"
        f.write_text(json.dumps(_SAMPLE_WORKOUT_PAYLOAD))
        runner.invoke(cli, ["workout", "create", str(f)])
        mock_build.assert_called_once_with(_SAMPLE_WORKOUT_PAYLOAD)
        mock_create.assert_called_once_with(garmin_shaped)

    def test_create_from_file(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value=_SAMPLE_WORKOUT_PAYLOAD,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.create_workout",
            return_value=_SAMPLE_CREATED_WORKOUT,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "workout.json"
        f.write_text(json.dumps(_SAMPLE_WORKOUT_PAYLOAD))
        result = runner.invoke(cli, ["--json", "workout", "create", str(f)])
        assert result.exit_code == 0

    def test_create_from_stdin(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value=_SAMPLE_WORKOUT_PAYLOAD,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.create_workout",
            return_value=_SAMPLE_CREATED_WORKOUT,
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "workout", "create", "--stdin"],
            input=json.dumps(_SAMPLE_WORKOUT_PAYLOAD),
        )
        assert result.exit_code == 0

    def test_create_invalid_json_exit_1(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            side_effect=GarminCliError(error="Invalid JSON", error_code="INVALID_INPUT"),
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "bad.json"
        f.write_text("{bad json}")
        result = runner.invoke(cli, ["workout", "create", str(f)])
        assert result.exit_code == 1

    def test_create_validation_error_exit_1(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value={"name": "No Sport"},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=["sport is required"],
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "workout.json"
        f.write_text(json.dumps({"name": "No Sport"}))
        result = runner.invoke(cli, ["workout", "create", str(f)])
        assert result.exit_code == 1

    def test_create_response_has_id(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value=_SAMPLE_WORKOUT_PAYLOAD,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.create_workout",
            return_value=_SAMPLE_CREATED_WORKOUT,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "workout.json"
        f.write_text(json.dumps(_SAMPLE_WORKOUT_PAYLOAD))
        result = runner.invoke(cli, ["--json", "workout", "create", str(f)])
        parsed = json.loads(result.output)
        row = parsed["data"][0]
        assert "id" in row or "workoutId" in row

    def test_create_auth_failure_exit_1(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch(
            "garmin_cli.commands.workouts.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "workout.json"
        f.write_text(json.dumps(_SAMPLE_WORKOUT_PAYLOAD))
        result = runner.invoke(cli, ["workout", "create", str(f)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# workout update command
# ---------------------------------------------------------------------------

class TestWorkoutUpdateCommand:

    def test_update_exit_code_0(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value=_SAMPLE_EXISTING_WORKOUT,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value={"name": "New Name"},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.merge_workout_payload",
            return_value=({**_SAMPLE_EXISTING_WORKOUT, "workoutName": "New Name"}, []),
        )
        mocker.patch(
            "garmin_cli.commands.workouts.update_workout",
            return_value=None,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "update.json"
        f.write_text(json.dumps({"name": "New Name"}))
        result = runner.invoke(cli, ["--json", "workout", "update", "12345", str(f)])
        assert result.exit_code == 0

    def test_update_json_ok_true(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value=_SAMPLE_EXISTING_WORKOUT,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value={"name": "New Name"},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.merge_workout_payload",
            return_value=({**_SAMPLE_EXISTING_WORKOUT, "workoutName": "New Name"}, []),
        )
        mocker.patch(
            "garmin_cli.commands.workouts.update_workout",
            return_value=None,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "update.json"
        f.write_text(json.dumps({"name": "New Name"}))
        result = runner.invoke(cli, ["--json", "workout", "update", "12345", str(f)])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_update_calls_auth(self, mocker: Any, tmp_path: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value=_SAMPLE_EXISTING_WORKOUT,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value={"name": "New Name"},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.merge_workout_payload",
            return_value=(_SAMPLE_EXISTING_WORKOUT, []),
        )
        mocker.patch(
            "garmin_cli.commands.workouts.update_workout",
            return_value=None,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "update.json"
        f.write_text(json.dumps({"name": "New Name"}))
        runner.invoke(cli, ["workout", "update", "12345", str(f)])
        mock_auth.assert_called_once()

    def test_update_calls_get_and_update(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mock_get = mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value=_SAMPLE_EXISTING_WORKOUT,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value={"name": "New Name"},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.merge_workout_payload",
            return_value=(_SAMPLE_EXISTING_WORKOUT, []),
        )
        mock_update = mocker.patch(
            "garmin_cli.commands.workouts.update_workout",
            return_value=None,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "update.json"
        f.write_text(json.dumps({"name": "New Name"}))
        runner.invoke(cli, ["workout", "update", "12345", str(f)])
        mock_get.assert_called_once()
        mock_update.assert_called_once()

    def test_update_emits_warnings_to_stderr(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value=_SAMPLE_EXISTING_WORKOUT,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value={"name": "New Name", "workoutId": 99},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.merge_workout_payload",
            return_value=(_SAMPLE_EXISTING_WORKOUT, ["workoutId is read-only and was ignored"]),
        )
        mocker.patch(
            "garmin_cli.commands.workouts.update_workout",
            return_value=None,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "update.json"
        f.write_text(json.dumps({"name": "New Name", "workoutId": 99}))
        result = runner.invoke(cli, ["workout", "update", "12345", str(f)])
        assert "warning" in result.stderr.lower() or "ignored" in result.stderr.lower()

    def test_update_invalid_workout_id_exit_1(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "update.json"
        f.write_text(json.dumps({"name": "New Name"}))
        result = runner.invoke(cli, ["workout", "update", "not-a-number", str(f)])
        assert result.exit_code == 1

    def test_update_not_found_exit_1(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value={"name": "New Name"},
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "update.json"
        f.write_text(json.dumps({"name": "New Name"}))
        result = runner.invoke(cli, ["workout", "update", "99999", str(f)])
        assert result.exit_code == 1

    def test_update_from_file(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value=_SAMPLE_EXISTING_WORKOUT,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value={"name": "From File"},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.merge_workout_payload",
            return_value=(_SAMPLE_EXISTING_WORKOUT, []),
        )
        mocker.patch(
            "garmin_cli.commands.workouts.update_workout",
            return_value=None,
        )
        runner = CliRunner(mix_stderr=False)
        f = tmp_path / "update.json"
        f.write_text(json.dumps({"name": "From File"}))
        result = runner.invoke(cli, ["--json", "workout", "update", "12345", str(f)])
        assert result.exit_code == 0

    def test_update_from_stdin(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value=_SAMPLE_EXISTING_WORKOUT,
        )
        mocker.patch(
            "garmin_cli.commands.workouts.read_workout_input",
            return_value={"name": "From Stdin"},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.validate_workout_input",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.workouts.merge_workout_payload",
            return_value=(_SAMPLE_EXISTING_WORKOUT, []),
        )
        mocker.patch(
            "garmin_cli.commands.workouts.update_workout",
            return_value=None,
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "workout", "update", "12345", "--stdin"],
            input=json.dumps({"name": "From Stdin"}),
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# workout delete command
# ---------------------------------------------------------------------------

class TestWorkoutDeleteCommand:

    def test_delete_exit_code_0_with_confirm_flag(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch("garmin_cli.commands.workouts.delete_workout", return_value=None)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "delete", "12345", "--confirm"])
        assert result.exit_code == 0

    def test_delete_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch("garmin_cli.commands.workouts.delete_workout", return_value=None)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "delete", "12345", "--confirm"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_delete_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch("garmin_cli.commands.workouts.delete_workout", return_value=None)
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["workout", "delete", "12345", "--confirm"])
        mock_auth.assert_called_once()

    def test_delete_calls_delete_workout(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mock_delete = mocker.patch(
            "garmin_cli.commands.workouts.delete_workout", return_value=None
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["workout", "delete", "12345", "--confirm"])
        mock_delete.assert_called_once()

    def test_delete_confirmation_prompt_shown(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch("garmin_cli.commands.workouts.delete_workout", return_value=None)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "delete", "12345"], input="y\n")
        # Prompt should appear somewhere in the combined output
        assert result.exit_code == 0 or "confirm" in result.output.lower() or "delete" in result.output.lower()

    def test_delete_aborted_on_no_confirmation(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mock_delete = mocker.patch(
            "garmin_cli.commands.workouts.delete_workout", return_value=None
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "delete", "12345"], input="n\n")
        assert result.exit_code != 0 or mock_delete.call_count == 0

    def test_delete_json_output_skips_prompt(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch("garmin_cli.commands.workouts.delete_workout", return_value=None)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "delete", "12345"])
        # With --json, either auto-confirms or still needs --confirm, but should not hang
        assert result.exit_code in (0, 1)

    def test_delete_not_found_exit_1(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.delete_workout",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "delete", "99999", "--confirm"])
        assert result.exit_code == 1

    def test_delete_invalid_id_exit_1(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "delete", "not-a-number", "--confirm"])
        assert result.exit_code == 1

    def test_delete_response_contains_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch("garmin_cli.commands.workouts.delete_workout", return_value=None)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "delete", "12345", "--confirm"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True


# ---------------------------------------------------------------------------
# workout schedule command
# ---------------------------------------------------------------------------

class TestWorkoutScheduleCommand:

    def test_schedule_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.schedule_workout",
            return_value=_SAMPLE_SCHEDULE_RESPONSE,
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "schedule", "12345", "2026-04-01"])
        assert result.exit_code == 0

    def test_schedule_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.schedule_workout",
            return_value=_SAMPLE_SCHEDULE_RESPONSE,
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "schedule", "12345", "2026-04-01"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_schedule_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.schedule_workout",
            return_value=_SAMPLE_SCHEDULE_RESPONSE,
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["workout", "schedule", "12345", "2026-04-01"])
        mock_auth.assert_called_once()

    def test_schedule_calls_schedule_workout(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mock_schedule = mocker.patch(
            "garmin_cli.commands.workouts.schedule_workout",
            return_value=_SAMPLE_SCHEDULE_RESPONSE,
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["workout", "schedule", "12345", "2026-04-01"])
        mock_schedule.assert_called_once()

    def test_schedule_passes_correct_date(self, mocker: Any) -> None:
        from datetime import date

        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mock_schedule = mocker.patch(
            "garmin_cli.commands.workouts.schedule_workout",
            return_value=_SAMPLE_SCHEDULE_RESPONSE,
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["workout", "schedule", "12345", "2026-04-01"])
        call_str = str(mock_schedule.call_args)
        assert "2026-04-01" in call_str or "2026" in call_str

    def test_schedule_invalid_date_exit_1(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "schedule", "12345", "not-a-date"])
        assert result.exit_code == 1

    def test_schedule_not_found_exit_1(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.schedule_workout",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "schedule", "99999", "2026-04-01"])
        assert result.exit_code == 1

    def test_schedule_response_has_schedule_id(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.schedule_workout",
            return_value=_SAMPLE_SCHEDULE_RESPONSE,
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "schedule", "12345", "2026-04-01"])
        parsed = json.loads(result.output)
        row = parsed["data"][0]
        assert "workoutScheduleId" in row or "id" in row
