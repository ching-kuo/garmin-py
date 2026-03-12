"""Regression tests for CLI fixes from the plan."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli


class TestWorkoutCalendarFixes:

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

    def test_calendar_json_includes_workout_id(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_calendar_range",
            return_value=[
                {
                    "date": "2026-03-12",
                    "workoutId": 987654,
                    "title": "Tempo Run",
                    "workoutTypeKey": "running",
                    "durationInSeconds": 3600,
                    "note": "Hard effort",
                }
            ],
        )
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["--json", "workout", "calendar", "--ahead", "7"])

        parsed = json.loads(result.output)
        assert parsed["data"][0]["id"] == 987654


class TestWorkoutGetFixes:

    def test_workout_get_json_includes_steps(self, mocker: Any, sample_workout_detail_raw: Any) -> None:
        mocker.patch("garmin_cli.commands.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.workouts.get_workout",
            return_value=sample_workout_detail_raw,
        )
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["--json", "workout", "get", "987654"])

        parsed = json.loads(result.output)
        assert parsed["data"][0]["steps_summary"] == "warmup > interval > cooldown"
        assert len(parsed["data"][0]["steps"]) == 3

    def test_workout_get_csv_uses_steps_summary_column(
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

        result = runner.invoke(cli, ["--format", "csv", "workout", "get", "987654"])

        assert result.exit_code == 0
        assert "steps_summary" in result.output
        assert "warmup > interval > cooldown" in result.output


class TestPerformanceFixes:

    def test_vo2max_json_uses_normalized_keys(self, mocker: Any, sample_vo2max_wrapped_raw: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_vo2max",
            return_value=sample_vo2max_wrapped_raw,
        )
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            ["--json", "performance", "vo2max", "--date", "2026-03-11"],
        )

        parsed = json.loads(result.output)
        assert parsed["data"] == [{"date": "2026-03-11", "vo2max": 52.0, "sport": "running"}]

    def test_vo2max_default_uses_latest_endpoint(self, mocker: Any, sample_vo2max_live_raw: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mock_latest = mocker.patch(
            "garmin_cli.commands.performance.get_latest_vo2max",
            return_value=sample_vo2max_live_raw,
        )
        mock_exact = mocker.patch("garmin_cli.commands.performance.get_vo2max")
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["--json", "performance", "vo2max"])

        assert result.exit_code == 0
        mock_latest.assert_called_once()
        mock_exact.assert_not_called()
        parsed = json.loads(result.output)
        assert parsed["data"] == [
            {"date": "2026-03-10", "vo2max": 54.0, "sport": "generic"},
            {"date": "2026-03-10", "vo2max": 55.0, "sport": "cycling"},
        ]

    def test_vo2max_default_limits_output_to_latest_day(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_latest_vo2max",
            return_value=[
                {
                    "generic": {
                        "calendarDate": "2026-03-10",
                        "vo2MaxValue": 54.0,
                    },
                    "cycling": {
                        "calendarDate": "2026-03-10",
                        "vo2MaxValue": 55.0,
                    },
                },
                {
                    "generic": {
                        "calendarDate": "2026-03-08",
                        "vo2MaxValue": 52.0,
                    }
                },
            ],
        )
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["--json", "performance", "vo2max"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["data"] == [
            {"date": "2026-03-10", "vo2max": 54.0, "sport": "generic"},
            {"date": "2026-03-10", "vo2max": 55.0, "sport": "cycling"},
        ]

    def test_zones_json_uses_normalized_keys(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_lactate_threshold",
            return_value={
                "sport": "running",
                "lactateThresholdHeartRate": 168,
                "lactateThresholdSpeed": 3.2,
            },
        )
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["--json", "performance", "zones"])

        parsed = json.loads(result.output)
        assert parsed["data"] == [{"sport": "running", "lt_hr_bpm": 168, "lt_pace": "5:12"}]

    def test_zones_json_uses_live_lactate_shape(
        self,
        mocker: Any,
        sample_lactate_threshold_live_raw: Any,
    ) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_lactate_threshold",
            return_value=sample_lactate_threshold_live_raw,
        )
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["--json", "performance", "zones"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["data"] == [{"sport": "running", "lt_hr_bpm": 177, "lt_pace": "4:26"}]


@pytest.mark.parametrize(
    ("command_name", "patch_name", "payload", "expected"),
    [
        (
            "body-battery",
            "get_body_battery_range",
            [{"bodyBatteryValuesArray": [["2026-03-11T08:00:00", 85, "CHARGED"], ["2026-03-11T14:00:00", 60, "DRAINING"]]}],
            {"date": "2026-03-11", "start_level": 85, "end_level": 60},
        ),
        (
            "stress",
            "get_stress_range",
            [{"stressValuesArray": [["2026-03-11T08:00:00", 25]], "avgStressLevel": 35, "maxStressLevel": 72}],
            {"date": "2026-03-11", "avg_stress": 35, "max_stress": 72},
        ),
        (
            "spo2",
            "get_spo2_range",
            [{"dateTime": "2026-03-11", "averageSpO2": 97, "lowestSpO2": 93}],
            {"date": "2026-03-11", "avg_spo2": 97, "lowest_spo2": 93},
        ),
        (
            "resting-hr",
            "get_resting_hr_range",
            [{"calendarDate": "2026-03-11", "restingHeartRateValue": 52}],
            {"date": "2026-03-11", "resting_hr": 52},
        ),
        (
            "readiness",
            "get_training_readiness_range",
            [{"calendarDate": "2026-03-11", "score": 68, "level": "MODERATE"}],
            {"date": "2026-03-11", "score": 68, "level": "MODERATE"},
        ),
    ],
)
def test_new_health_range_commands(
    mocker: Any,
    command_name: str,
    patch_name: str,
    payload: list[dict[str, Any]],
    expected: dict[str, Any],
) -> None:
    mocker.patch("garmin_cli.commands.health.ensure_authenticated")
    mocker.patch(f"garmin_cli.commands.health.{patch_name}", return_value=payload)
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(cli, ["--json", "health", command_name, "--days", "1"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["data"] == [expected]


def test_health_status_single_day_command(mocker: Any) -> None:
    mocker.patch("garmin_cli.commands.health.ensure_authenticated")
    mocker.patch(
        "garmin_cli.commands.health.get_training_status",
        return_value={
            "calendarDate": "2026-03-11",
            "trainingStatusType": "PRODUCTIVE",
            "trainingLoadType": "OPTIMAL",
        },
    )
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(cli, ["--json", "health", "status", "--date", "2026-03-11"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["data"] == [
        {
            "date": "2026-03-11",
            "training_status": "PRODUCTIVE",
            "load_type": "OPTIMAL",
        }
    ]
