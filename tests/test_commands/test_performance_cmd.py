"""CLI integration tests for performance commands using CliRunner."""
from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli


# ---------------------------------------------------------------------------
# performance personal-records command
# ---------------------------------------------------------------------------

class TestPerformancePersonalRecordsCommand:

    def test_personal_records_json_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_personal_records",
            return_value=[
                {
                    "typeId": 1,
                    "value": 219.76,
                    "activityType": "running",
                    "activityId": 111,
                    "activityName": "Track Intervals",
                    "activityStartDateTimeLocalFormatted": "2026-04-01T06:00:00.0",
                }
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "personal-records"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert parsed["count"] == 1
        assert parsed["data"][0]["label"] == "fastest_1km_s"
        assert parsed["data"][0]["date"] == "2026-04-01"

    def test_personal_records_empty_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_personal_records",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "personal-records"])
        assert result.exit_code == 0
        assert json.loads(result.output)["count"] == 0


# ---------------------------------------------------------------------------
# Single-call commands: shared envelope, auth-failure, and table behavior
# ---------------------------------------------------------------------------

_RACE_PREDICTION_ROWS = [
    {"race_type": "5K", "predicted_time_seconds": 1500, "distance_meters": 5000},
    {"race_type": "10K", "predicted_time_seconds": 3200, "distance_meters": 10000},
    {"race_type": "HalfMarathon", "predicted_time_seconds": 7200, "distance_meters": 21097},
    {"race_type": "Marathon", "predicted_time_seconds": 15000, "distance_meters": 42195},
]


@pytest.mark.parametrize(
    ("command", "endpoint", "serializer", "rows"),
    [
        ("thresholds", "get_all_thresholds", "serialize_thresholds", []),
        ("thresholds", "get_all_thresholds", "serialize_thresholds", [{"sport": "running"}, {"sport": "cycling"}]),
        ("race-predictions", "get_race_predictions", "serialize_race_predictions", []),
        ("race-predictions", "get_race_predictions", "serialize_race_predictions", _RACE_PREDICTION_ROWS),
    ],
)
def test_single_call_command_json_envelope(
    mocker: Any, command: str, endpoint: str, serializer: str, rows: list[dict[str, Any]]
) -> None:
    mock_auth = mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
    mocker.patch(f"garmin_cli.commands.performance.{endpoint}", return_value={})
    mocker.patch(f"garmin_cli.commands.performance.{serializer}", return_value=rows)

    result = CliRunner(mix_stderr=False).invoke(cli, ["--json", "performance", command])

    assert result.exit_code == 0
    mock_auth.assert_called_once()
    parsed = json.loads(result.output)
    assert parsed["ok"] is True
    assert parsed["count"] == len(rows)
    assert parsed["data"] == rows
    assert parsed.get("date_range") is None


@pytest.mark.parametrize("command", ["thresholds", "vo2max", "zones", "race-predictions"])
@pytest.mark.parametrize("json_mode", [False, True], ids=("table", "json"))
def test_single_call_command_auth_failure(mocker: Any, command: str, json_mode: bool) -> None:
    from garmin_cli.exceptions import GarminCliError

    mocker.patch(
        "garmin_cli.commands.performance.ensure_authenticated",
        side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
    )
    args = ["--json"] if json_mode else []

    result = CliRunner(mix_stderr=False).invoke(cli, [*args, "performance", command])

    assert result.exit_code == 1
    if json_mode:
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"


def test_race_predictions_table_output_not_json(mocker: Any) -> None:
    mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
    mocker.patch("garmin_cli.commands.performance.get_race_predictions", return_value={})
    mocker.patch(
        "garmin_cli.commands.performance.serialize_race_predictions",
        return_value=[{"race_type": "5K", "predicted_time_seconds": 1500, "distance_meters": 5000}],
    )

    result = CliRunner(mix_stderr=False).invoke(cli, ["performance", "race-predictions"])

    assert result.exit_code == 0
    assert "5K" in result.output
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.output)


@pytest.mark.parametrize("json_mode", [False, True], ids=("table", "json"))
def test_thresholds_server_error(mocker: Any, json_mode: bool) -> None:
    from garmin_cli.exceptions import GarminCliError

    mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
    mocker.patch(
        "garmin_cli.commands.performance.get_all_thresholds",
        side_effect=GarminCliError(error="Server error", error_code="SERVER_ERROR"),
    )
    args = ["--json"] if json_mode else []

    result = CliRunner(mix_stderr=False).invoke(cli, [*args, "performance", "thresholds"])

    assert result.exit_code == 1
    if json_mode:
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "SERVER_ERROR"


# ---------------------------------------------------------------------------
# performance vo2max command
# ---------------------------------------------------------------------------

class TestPerformanceVo2maxCommand:

    def test_vo2max_json_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.services.performance.get_vo2max",
            return_value={"vo2MaxValue": 52.0},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "performance", "vo2max", "--date", "2026-03-11"]
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_vo2max_default_to_today(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mock_latest = mocker.patch(
            "garmin_cli.services.performance.get_latest_vo2max",
            return_value=[{"generic": {"calendarDate": "2026-03-10", "vo2MaxValue": 52.0}}],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["--json", "performance", "vo2max"])
        mock_latest.assert_called_once_with()

    def test_vo2max_table_output_handles_list_payload(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.services.performance.get_vo2max",
            return_value=[{"calendarDate": "2026-03-11", "vo2MaxValue": 52.0}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "vo2max", "--date", "2026-03-11"])
        assert result.exit_code == 0
        assert "2026-03-11" in result.output or "52.0" in result.output

    def test_vo2max_default_limits_output_to_latest_day(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.services.performance.get_latest_vo2max",
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


# ---------------------------------------------------------------------------
# performance zones command
# ---------------------------------------------------------------------------

class TestPerformanceZonesCommand:

    def test_zones_json_ok(self, mocker: Any, sample_zone_tables_raw: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_zone_tables",
            return_value=sample_zone_tables_raw,
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "zones"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert parsed["data"][0] == {
            "kind": "heart_rate", "sport": "default", "zone": 1, "low": 118, "high": 143, "unit": "bpm",
        }

    def test_zones_table_output(self, mocker: Any, sample_zone_tables_raw: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_zone_tables",
            return_value=sample_zone_tables_raw,
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "zones"])
        assert result.exit_code == 0
        assert "cycling" in result.output and "351" in result.output


# ---------------------------------------------------------------------------
# --garmin-home global flag
# ---------------------------------------------------------------------------

class TestGarminHomeFlag:

    def test_garmin_home_flag_passed_to_config(self, mocker: Any) -> None:
        mock_auth = mocker.patch(
            "garmin_cli.commands.performance.ensure_authenticated"
        )
        mocker.patch(
            "garmin_cli.commands.performance.get_all_thresholds",
            return_value={"thresholds": []},
        )
        mocker.patch(
            "garmin_cli.commands.performance.serialize_thresholds",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(
            cli,
            ["--garmin-home", "/custom/garmin", "performance", "thresholds"],
        )
        # Auth should be called; config with custom session home should be passed
        assert mock_auth.called
        call_args = mock_auth.call_args
        config = call_args[0][0]
        assert config.garth_home == "/custom/garmin"

    def test_removed_garth_home_option_is_rejected(self, mocker: Any) -> None:
        mock_auth = mocker.patch(
            "garmin_cli.commands.performance.ensure_authenticated"
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--garth-home", "/compat/garth", "performance", "thresholds"],
        )
        assert result.exit_code != 0
        assert "no such option" in (result.output + result.stderr).lower()
        assert not mock_auth.called
