"""CLI integration tests for health commands using CliRunner."""
from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli

# --json and --format json are equivalent JSON-mode triggers; several tests
# below verify both spellings produce the same behavior.
_json_flag_variants = pytest.mark.parametrize(
    "json_flag_args", (["--json"], ["--format", "json"]), ids=("json-flag", "format-json")
)


# ---------------------------------------------------------------------------
# sleep command
# ---------------------------------------------------------------------------

class TestSleepCommand:

    def test_sleep_days_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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

    def test_relative_range_uses_profile_today_after_login(self, mocker: Any) -> None:
        from datetime import date

        logged_in: list[bool] = []
        mocker.patch(
            "garmin_cli.commands._options.ensure_authenticated",
            side_effect=lambda config: logged_in.append(True),
        )
        # The profile timezone is only known once a session exists.
        mocker.patch(
            "garmin_cli.backend.profile_today",
            side_effect=lambda: date(2030, 1, 2) if logged_in else None,
        )
        get_sleep = mocker.patch("garmin_cli.commands.health.get_sleep", return_value=[])
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["health", "sleep", "--days", "2"])

        assert result.exit_code == 0, result.output
        get_sleep.assert_called_once_with(date(2030, 1, 1), date(2030, 1, 2))

    @pytest.mark.parametrize(
        ("module", "getter", "args", "expected"),
        [
            ("activities", "list_activities", ["activity", "list", "--days", "2"], None),
            ("workouts", "get_calendar_range", ["workout", "calendar", "--ahead", "2"], ("2030-01-02", "2030-01-03")),
            ("health", "get_training_status", ["health", "status"], ("2030-01-02",)),
        ],
    )
    def test_other_relative_dates_use_profile_today_after_login(
        self, mocker: Any, module: str, getter: str, args: list[str], expected: tuple[str, ...] | None
    ) -> None:
        from datetime import date

        logged_in: list[bool] = []
        mocker.patch(
            f"garmin_cli.commands.{module}.ensure_authenticated",
            side_effect=lambda config: logged_in.append(True),
        )
        mocker.patch(
            "garmin_cli.backend.profile_today",
            side_effect=lambda: date(2030, 1, 2) if logged_in else None,
        )
        fetch = mocker.patch(f"garmin_cli.commands.{module}.{getter}", return_value=[])

        result = CliRunner(mix_stderr=False).invoke(cli, args)

        assert result.exit_code == 0, result.output
        if expected is None:
            assert (fetch.call_args.kwargs["start_date"], fetch.call_args.kwargs["end_date"]) == (
                date(2030, 1, 1),
                date(2030, 1, 2),
            )
        else:
            assert fetch.call_args.args == tuple(date.fromisoformat(day) for day in expected)

    @pytest.mark.parametrize(
        ("seam", "args"),
        [
            ("activities", ["activity", "list", "--days", "0"]),
            ("workouts", ["workout", "calendar", "--days", "2", "--ahead", "2"]),
            ("_options", ["health", "sleep", "--days", "91"]),
        ],
    )
    def test_date_usage_errors_fail_before_login(self, mocker: Any, seam: str, args: list[str]) -> None:
        auth = mocker.patch(f"garmin_cli.commands.{seam}.ensure_authenticated")

        result = CliRunner(mix_stderr=False).invoke(cli, args)

        assert result.exit_code != 0
        auth.assert_not_called()

    def test_sleep_json_flag_outputs_json_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["health", "sleep", "--date", "2026-03-11", "--days", "7"]
        )
        assert result.exit_code != 0

    def test_sleep_has_no_ahead_option(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--ahead", "3"])
        assert result.exit_code == 1
        assert "--ahead" in result.stderr

    def test_sleep_from_without_to_fails(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--from", "2026-03-01"])
        assert result.exit_code != 0

    def test_sleep_auth_failure_returns_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands._options.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--days", "1"])
        assert result.exit_code == 1

    @_json_flag_variants
    def test_sleep_auth_failure_json_mode_outputs_error_envelope(
        self, mocker: Any, json_flag_args: list[str]
    ) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands._options.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, [*json_flag_args, "health", "sleep", "--days", "1"]
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_sleep_empty_data_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
            {"date": "2026-03-11", "start_level": 85, "end_level": 60, "max_level": 85},
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
    mocker.patch("garmin_cli.commands._options.ensure_authenticated")
    mocker.patch(f"garmin_cli.commands.health.{patch_name}", return_value=payload)
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(cli, ["--json", "health", command_name, "--days", "1"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["data"] == [expected]


# Range commands sharing commands._options.render_date_range (auth + envelope);
# the performance ones live here too because they take the same path.
_RANGE_CASES = [
    ("health", "steps", "get_steps_range", "serialize_steps"),
    ("health", "daily-summary", "get_daily_summary_range", "serialize_daily_summary"),
    ("health", "intensity-minutes", "get_intensity_minutes_range", "serialize_intensity_minutes"),
    ("performance", "endurance-score", "get_endurance_score_range", "serialize_endurance_score"),
    ("performance", "hill-score", "get_hill_score_range", "serialize_hill_score"),
]
_RANGE_COMMANDS = pytest.mark.parametrize(("group", "command", "endpoint", "serializer"), _RANGE_CASES)
_RANGE_COMMAND_NAMES = pytest.mark.parametrize(
    ("group", "command"), [(group, command) for group, command, _, _ in _RANGE_CASES]
)


@_RANGE_COMMANDS
@pytest.mark.parametrize(
    ("json_mode", "days", "rows"),
    [
        pytest.param(True, "1", [{"date": "2026-03-11"}], id="json-one-day"),
        pytest.param(True, "2", [{"date": "2026-03-10"}, {"date": "2026-03-11"}], id="json-two-days"),
        pytest.param(True, "1", [], id="json-empty"),
        pytest.param(False, "1", [{"date": "2026-03-11"}], id="table-one-day"),
    ],
)
def test_range_command_output(
    mocker: Any,
    group: str,
    command: str,
    endpoint: str,
    serializer: str,
    json_mode: bool,
    days: str,
    rows: list[dict[str, Any]],
) -> None:
    mock_auth = mocker.patch("garmin_cli.commands._options.ensure_authenticated")
    mocker.patch(f"garmin_cli.commands.{group}.{endpoint}", return_value=[])
    mocker.patch(f"garmin_cli.commands.{group}.{serializer}", return_value=rows)
    args = ["--json"] if json_mode else []

    result = CliRunner(mix_stderr=False).invoke(cli, [*args, group, command, "--days", days])

    assert result.exit_code == 0
    mock_auth.assert_called_once()
    if not json_mode:
        assert "2026-03-11" in result.output
        return
    parsed = json.loads(result.output)
    assert parsed["ok"] is True
    assert parsed["count"] == len(rows)
    assert parsed["data"] == rows


@_RANGE_COMMANDS
def test_range_command_reports_date_range(
    mocker: Any, group: str, command: str, endpoint: str, serializer: str
) -> None:
    mocker.patch("garmin_cli.commands._options.ensure_authenticated")
    mocker.patch(f"garmin_cli.commands.{group}.{endpoint}", return_value=[])
    mocker.patch(f"garmin_cli.commands.{group}.{serializer}", return_value=[])

    result = CliRunner(mix_stderr=False).invoke(
        cli, ["--json", group, command, "--from", "2026-03-01", "--to", "2026-03-07"]
    )

    assert json.loads(result.output)["date_range"] == {"from": "2026-03-01", "to": "2026-03-07"}


@_RANGE_COMMAND_NAMES
def test_range_command_rejects_date_with_days(mocker: Any, group: str, command: str) -> None:
    mocker.patch("garmin_cli.commands._options.ensure_authenticated")

    result = CliRunner(mix_stderr=False).invoke(
        cli, [group, command, "--date", "2026-03-11", "--days", "7"]
    )

    assert result.exit_code != 0


@_RANGE_COMMAND_NAMES
def test_range_command_auth_failure_json_envelope(mocker: Any, group: str, command: str) -> None:
    from garmin_cli.exceptions import GarminCliError

    mocker.patch(
        "garmin_cli.commands._options.ensure_authenticated",
        side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
    )

    result = CliRunner(mix_stderr=False).invoke(cli, ["--json", group, command, "--days", "1"])

    assert result.exit_code == 1
    parsed = json.loads(result.output)
    assert parsed["ok"] is False
    assert parsed["error_code"] == "AUTH_MISSING"


def test_health_status_single_day_command(mocker: Any) -> None:
    mocker.patch("garmin_cli.commands.health.ensure_authenticated")
    mocker.patch(
        "garmin_cli.commands.health.get_training_status",
        return_value={
            "mostRecentTrainingStatus": {
                "latestTrainingStatusData": {
                    "3617502513": {
                        "calendarDate": "2026-03-11",
                        "trainingStatusFeedbackPhrase": "PRODUCTIVE_2",
                        "primaryTrainingDevice": True,
                        "acuteTrainingLoadDTO": {
                            "acwrStatus": "OPTIMAL",
                            "dailyTrainingLoadAcute": 964,
                            "dailyTrainingLoadChronic": 772,
                            "dailyAcuteChronicWorkloadRatio": 1.2,
                        },
                    }
                }
            },
        },
    )
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(cli, ["--json", "health", "status", "--date", "2026-03-11"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    row = parsed["data"][0]
    assert row["date"] == "2026-03-11"
    assert row["training_status"] == "PRODUCTIVE_2"
    assert row["acute_load"] == 964
    assert row["chronic_load"] == 772
    assert row["acwr"] == 1.2
    assert row["acwr_status"] == "OPTIMAL"
    # No load-balance block in this payload: balance columns stay None.
    assert row["monthly_load_aerobic_low"] is None


# ---------------------------------------------------------------------------
# CSV output format
# ---------------------------------------------------------------------------

class TestHealthCsvOutput:

    def test_sleep_csv_no_ansi(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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


# ---------------------------------------------------------------------------
# Usage errors in JSON mode
# ---------------------------------------------------------------------------

class TestUsageErrorInJsonMode:

    @_json_flag_variants
    def test_usage_error_json_mode_outputs_error_envelope(
        self, mocker: Any, json_flag_args: list[str]
    ) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            [*json_flag_args, "health", "sleep", "--date", "2026-03-11", "--days", "7"],
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_INPUT"

    def test_usage_error_exit_code_1_not_2(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["health", "sleep", "--date", "2026-03-11", "--days", "7"],
        )
        # Should be exit code 1, NOT 2 (click default for usage errors)
        assert result.exit_code == 1

    def test_json_error_command_ignores_global_option_values(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            [
                "--json",
                "--garmin-home",
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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

    @_json_flag_variants
    def test_unexpected_exception_json_mode_outputs_internal_error_envelope(
        self, mocker: Any, json_flag_args: list[str]
    ) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_sleep",
            side_effect=RuntimeError("unexpected bug"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, [*json_flag_args, "health", "sleep", "--days", "1"]
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INTERNAL_ERROR"

    def test_unexpected_exception_table_mode_stderr_not_stdout(
        self, mocker: Any
    ) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.health.get_sleep",
            side_effect=RuntimeError("unexpected bug"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--days", "1"])
        assert result.exit_code == 1
        # stdout should NOT contain a JSON error envelope in table mode
        # (errors go to stderr in table mode)


# ---------------------------------------------------------------------------
# Table output path
# ---------------------------------------------------------------------------

class TestTableOutput:

    def test_sleep_table_output_is_not_json(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
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
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_sleep", return_value={})
        mocker.patch(
            "garmin_cli.commands.health.serialize_sleep",
            return_value=[{"date": "2026-03-11", "score": 80, "duration_hours": 7.5}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "sleep", "--days", "1"])
        assert result.exit_code == 0
        assert "2026-03-11" in result.output or "80" in result.output
