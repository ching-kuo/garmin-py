"""CLI integration tests for workout commands using CliRunner."""
from __future__ import annotations

from datetime import date, timedelta
import json
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli


# ---------------------------------------------------------------------------
# workout list command
# ---------------------------------------------------------------------------

class TestWorkoutListCommand:

    def test_list_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch("garmin_cli.commands.workouts.list_workouts", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "list"])
        assert result.exit_code == 0

    def test_list_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.list_workouts",
            return_value=[{"workoutId": 1, "workoutName": "Tempo"}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "list"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_list_limit_flag_passed(self, mocker: Any) -> None:
        mock_list = mocker.patch(
            "garmin_cli.commands.workouts.list_workouts", return_value=[]
        )
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["workout", "list", "--limit", "10"])
        mock_list.assert_called_once_with(limit=10)

    def test_list_empty_data_count_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch("garmin_cli.commands.workouts.list_workouts", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "list"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 0

    def test_list_auth_failure_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.workouts.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "list"])
        assert result.exit_code == 1

    def test_list_auth_failure_json_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.workouts.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "list"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is False

    @pytest.mark.parametrize("limit_value", ["0", "-5"])
    def test_list_invalid_limit_exit_1(self, mocker: Any, limit_value: str) -> None:
        """Regression: --limit 0 or negative must be rejected before hitting the API."""
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mock_list = mocker.patch("garmin_cli.commands.workouts.list_workouts")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "list", "--limit", limit_value])
        assert result.exit_code == 1
        mock_list.assert_not_called()

    def test_list_limit_zero_json_error_code(self, mocker: Any) -> None:
        """Regression: --limit 0 with --json returns INVALID_INPUT error code."""
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "list", "--limit", "0"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_INPUT"

    def test_list_limit_one_accepted(self, mocker: Any) -> None:
        """Boundary: --limit 1 is valid and should proceed normally."""
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch("garmin_cli.commands.workouts.list_workouts", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "list", "--limit", "1"])
        assert result.exit_code == 0

    def test_list_table_output_contains_workout_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.list_workouts",
            return_value=[
                {
                    "workoutId": 987654,
                    "workoutName": "Tempo Run",
                    "sportType": {"sportTypeKey": "running"},
                    "estimatedDurationInSecs": 3600,
                    "description": "4x10min at threshold pace",
                }
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "list"])
        assert result.exit_code == 0
        assert "Tempo Run" in result.output


# ---------------------------------------------------------------------------
# workout get command
# ---------------------------------------------------------------------------

class TestWorkoutGetCommand:

    def test_get_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value={"workoutId": 987654, "workoutName": "Tempo Run"},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "get", "987654"])
        assert result.exit_code == 0

    def test_get_json_envelope_ok(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value={"workoutId": 987654},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "get", "987654"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_get_singleton_in_list(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value={"workoutId": 987654, "workoutName": "Tempo"},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "get", "987654"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 1
        assert isinstance(parsed["data"], list)

    def test_get_not_found_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "get", "99999"])
        assert result.exit_code == 1

    def test_get_not_found_json_error(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "get", "99999"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "NOT_FOUND"

    def test_get_csv_output_contains_workout_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value={
                "workoutId": 987654,
                "workoutName": "Tempo Run",
                "sportType": {"sportTypeKey": "running"},
                "estimatedDurationInSecs": 3600,
                "description": "4x10min at threshold pace",
            },
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--format", "csv", "workout", "get", "987654"])
        assert result.exit_code == 0
        assert "Tempo Run" in result.output

    def test_get_json_includes_steps_and_summary(
        self,
        mocker: Any,
        sample_workout_detail_raw: Any,
    ) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value=sample_workout_detail_raw,
        )
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["--json", "workout", "get", "987654"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["data"][0]["steps_summary"] == "warmup > interval > cooldown"
        assert len(parsed["data"][0]["steps"]) == 3


# ---------------------------------------------------------------------------
# workout calendar command
# ---------------------------------------------------------------------------

class TestWorkoutCalendarCommand:

    def test_calendar_ahead_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_calendar_range",
            return_value={"calendarItems": []},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.serialize_calendar_workout",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "calendar", "--ahead", "7"])
        assert result.exit_code == 0

    def test_calendar_defaults_to_seven_days_ahead(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mock_calendar = mocker.patch(
            "garmin_cli.commands.workouts.get_calendar_range",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["--json", "workout", "calendar"])

        assert result.exit_code == 0
        assert mock_calendar.call_args[0] == (
            date.today(),
            date.today() + timedelta(days=6),
        )

    def test_calendar_json_envelope_ok(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_calendar_range",
            return_value={"calendarItems": [{"date": "2026-03-12"}]},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.serialize_calendar_workout",
            return_value=[{"date": "2026-03-12", "name": "Tempo Run"}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "calendar", "--ahead", "7"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_calendar_days_flag(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mock_calendar = mocker.patch(
            "garmin_cli.commands.workouts.get_calendar_range",
            return_value={"calendarItems": []},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.serialize_calendar_workout",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["workout", "calendar", "--days", "7"])
        assert mock_calendar.called

    def test_calendar_from_to_flags(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mock_calendar = mocker.patch(
            "garmin_cli.commands.workouts.get_calendar_range",
            return_value={"calendarItems": []},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.serialize_calendar_workout",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(
            cli,
            ["workout", "calendar", "--from", "2026-03-01", "--to", "2026-03-14"],
        )
        assert mock_calendar.called

    def test_calendar_conflict_days_ahead_exit_1(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["workout", "calendar", "--days", "7", "--ahead", "7"]
        )
        assert result.exit_code == 1

    def test_calendar_range_over_90_days_exit_1(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            [
                "workout",
                "calendar",
                "--from",
                "2026-01-01",
                "--to",
                "2026-04-15",
            ],
        )
        assert result.exit_code == 1

    def test_calendar_auth_error_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.workouts.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["workout", "calendar", "--ahead", "7"])
        assert result.exit_code == 1

    def test_calendar_count_matches_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_calendar_range",
            return_value={"calendarItems": [{}, {}]},
        )
        mocker.patch(
            "garmin_cli.commands.workouts.serialize_calendar_workout",
            return_value=[{"date": "d1"}, {"date": "d2"}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "workout", "calendar", "--ahead", "7"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 2
        assert len(parsed["data"]) == 2
