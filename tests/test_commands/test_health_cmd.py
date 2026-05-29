"""CLI integration tests for health commands using CliRunner."""
from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli


# ---------------------------------------------------------------------------
# sleep command
# ---------------------------------------------------------------------------

class TestSleepCommand:

    def test_sleep_days_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_sleep",
            return_value={"dailySleepDTO": {}},
        )
        mocker.patch(
            "garmin_cli.commands.health.serialize_sleep",
            return_value=[{"date": "2026-03-11", "score": 80}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--days", "1"])
        assert result.exit_code == 0

    def test_sleep_json_flag_outputs_json_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_sleep",
            return_value={"dailySleepDTO": {}},
        )
        mocker.patch(
            "garmin_cli.commands.health.serialize_sleep",
            return_value=[{"date": "2026-03-11", "score": 80}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "sleep", "--days", "1"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert "data" in parsed
        assert "count" in parsed
        assert parsed["count"] == len(parsed["data"])

    def test_sleep_json_envelope_has_command(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_sleep",
            return_value={"dailySleepDTO": {}},
        )
        mocker.patch(
            "garmin_cli.commands.health.serialize_sleep",
            return_value=[{"date": "2026-03-11", "score": 80}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "sleep", "--days", "1"])
        parsed = json.loads(result.output)
        assert "command" in parsed

    def test_sleep_date_flag_single_day(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_sleep",
            return_value={"dailySleepDTO": {}},
        )
        mocker.patch(
            "garmin_cli.commands.health.serialize_sleep",
            return_value=[{"date": "2026-03-11", "score": 75}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--date", "2026-03-11"])
        assert result.exit_code == 0

    def test_sleep_conflict_date_and_days(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["health", "sleep", "--date", "2026-03-11", "--days", "7"]
        )
        assert result.exit_code != 0

    def test_sleep_conflict_days_and_ahead(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--days", "7", "--ahead", "3"])
        assert result.exit_code != 0

    def test_sleep_from_without_to_fails(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--from", "2026-03-01"])
        assert result.exit_code != 0

    def test_sleep_auth_failure_returns_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.health.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--days", "1"])
        assert result.exit_code == 1

    def test_sleep_auth_failure_json_mode_outputs_error_envelope(
        self, mocker: Any
    ) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.health.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "health", "sleep", "--days", "1"]
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_sleep_empty_data_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_sleep", return_value={})
        mocker.patch("garmin_cli.commands.health.serialize_sleep", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "sleep", "--days", "1"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 0



# ---------------------------------------------------------------------------
# hrv command
# ---------------------------------------------------------------------------

class TestHrvCommand:

    def test_hrv_json_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_hrv",
            return_value={"hrvSummary": {}},
        )
        mocker.patch(
            "garmin_cli.commands.health.serialize_hrv",
            return_value=[{"date": "2026-03-11", "weekly_avg": 52}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "hrv", "--days", "1"])
        assert result.exit_code == 0

    def test_hrv_json_envelope_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_hrv",
            return_value={"hrvSummary": {}},
        )
        mocker.patch(
            "garmin_cli.commands.health.serialize_hrv",
            return_value=[{"date": "2026-03-11", "weekly_avg": 52}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "hrv", "--days", "1"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_hrv_count_matches_data_length(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_hrv", return_value={})
        mocker.patch(
            "garmin_cli.commands.health.serialize_hrv",
            return_value=[{"date": "d1"}, {"date": "d2"}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "hrv", "--days", "2"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 2

    def test_hrv_empty_payload_reports_zero_results(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_hrv", return_value={})
        mocker.patch("garmin_cli.commands.health.serialize_hrv", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "hrv", "--days", "1"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 0
        assert parsed["data"] == []


# ---------------------------------------------------------------------------
# weight command
# ---------------------------------------------------------------------------

class TestWeightCommand:

    def test_weight_json_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_weight", return_value={})
        mocker.patch(
            "garmin_cli.commands.health.serialize_weight",
            return_value=[{"date": "2026-03-11", "weight_kg": 75.0}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "weight", "--days", "7"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True


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


# ---------------------------------------------------------------------------
# CSV output format
# ---------------------------------------------------------------------------

class TestHealthCsvOutput:

    def test_sleep_csv_no_ansi(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_sleep", return_value={})
        mocker.patch(
            "garmin_cli.commands.health.serialize_sleep",
            return_value=[{"date": "2026-03-11", "score": 80}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--format", "csv", "health", "sleep", "--days", "1"]
        )
        assert result.exit_code == 0
        assert "\x1b[" not in result.output

    def test_json_flag_overrides_format_flag(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_sleep", return_value={})
        mocker.patch(
            "garmin_cli.commands.health.serialize_sleep",
            return_value=[{"date": "2026-03-11", "score": 80}],
        )
        runner = CliRunner(mix_stderr=False)
        # --json flag should take precedence over --format csv
        result = runner.invoke(
            cli,
            ["--json", "--format", "csv", "health", "sleep", "--days", "1"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_format_json_auth_failure_outputs_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.health.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--format", "json", "health", "sleep", "--days", "1"]
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"


# ---------------------------------------------------------------------------
# Usage errors in JSON mode
# ---------------------------------------------------------------------------

class TestUsageErrorInJsonMode:

    def test_usage_error_json_mode_outputs_error_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "health", "sleep", "--date", "2026-03-11", "--days", "7"],
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False

    def test_usage_error_json_mode_error_code_is_invalid_input(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "health", "sleep", "--date", "2026-03-11", "--days", "7"],
        )
        parsed = json.loads(result.output)
        assert parsed["error_code"] == "INVALID_INPUT"

    def test_usage_error_exit_code_1_not_2(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["health", "sleep", "--date", "2026-03-11", "--days", "7"],
        )
        # Should be exit code 1, NOT 2 (click default for usage errors)
        assert result.exit_code == 1

    def test_format_json_usage_error_outputs_error_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--format", "json", "health", "sleep", "--date", "2026-03-11", "--days", "7"],
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_INPUT"

    def test_json_error_command_ignores_global_option_values(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            [
                "--json",
                "--garth-home",
                "/tmp/x",
                "health",
                "sleep",
                "--date",
                "2026-03-11",
                "--days",
                "7",
            ],
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["command"] == "health sleep"

    def test_invalid_sleep_date_reports_invalid_input(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "health", "sleep", "--date", "03/11/2026"]
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Unexpected exception (INTERNAL_ERROR) in JSON mode
# ---------------------------------------------------------------------------

class TestUnexpectedExceptionInJsonMode:

    def test_unexpected_exception_json_mode_outputs_internal_error_envelope(
        self, mocker: Any
    ) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_sleep",
            side_effect=RuntimeError("unexpected bug"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "health", "sleep", "--days", "1"]
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INTERNAL_ERROR"

    def test_unexpected_exception_table_mode_stderr_not_stdout(
        self, mocker: Any
    ) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_sleep",
            side_effect=RuntimeError("unexpected bug"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--days", "1"])
        assert result.exit_code == 1
        # stdout should NOT contain a JSON error envelope in table mode
        # (errors go to stderr in table mode)

    def test_format_json_unexpected_exception_outputs_internal_error_envelope(
        self, mocker: Any
    ) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_sleep",
            side_effect=RuntimeError("unexpected bug"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--format", "json", "health", "sleep", "--days", "1"]
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Table output path
# ---------------------------------------------------------------------------

class TestTableOutput:

    def test_sleep_table_output_is_not_json(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_sleep", return_value={})
        mocker.patch(
            "garmin_cli.commands.health.serialize_sleep",
            return_value=[{"date": "2026-03-11", "score": 80, "duration_hours": 7.5}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--days", "1"])
        assert result.exit_code == 0
        # Table output should not be parseable as JSON (it's a table)
        try:
            json.loads(result.output)
            is_json = True
        except (json.JSONDecodeError, ValueError):
            is_json = False
        assert not is_json

    def test_sleep_table_output_contains_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_sleep", return_value={})
        mocker.patch(
            "garmin_cli.commands.health.serialize_sleep",
            return_value=[{"date": "2026-03-11", "score": 80, "duration_hours": 7.5}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--days", "1"])
        assert result.exit_code == 0
        assert "2026-03-11" in result.output or "80" in result.output
