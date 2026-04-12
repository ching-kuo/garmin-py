"""CLI integration tests for performance commands using CliRunner."""
from __future__ import annotations

import json
from typing import Any

from click.testing import CliRunner

from garmin_cli.cli import cli


# ---------------------------------------------------------------------------
# performance thresholds command
# ---------------------------------------------------------------------------

class TestPerformanceThresholdsCommand:

    def test_thresholds_calls_auth(self, mocker: Any) -> None:
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
        runner.invoke(cli, ["performance", "thresholds"])
        mock_auth.assert_called_once()

    def test_thresholds_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_all_thresholds",
            return_value={"thresholds": []},
        )
        mocker.patch(
            "garmin_cli.commands.performance.serialize_thresholds",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "thresholds"])
        assert result.exit_code == 0

    def test_thresholds_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_all_thresholds",
            return_value={"thresholds": [{"sport": "running"}]},
        )
        mocker.patch(
            "garmin_cli.commands.performance.serialize_thresholds",
            return_value=[{"sport": "running", "lt_hr_bpm": 168}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "thresholds"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_thresholds_count_matches_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_all_thresholds",
            return_value={"thresholds": [{}, {}]},
        )
        mocker.patch(
            "garmin_cli.commands.performance.serialize_thresholds",
            return_value=[{"sport": "running"}, {"sport": "cycling"}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "thresholds"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 2
        assert len(parsed["data"]) == 2

    def test_thresholds_auth_failure_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.performance.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "thresholds"])
        assert result.exit_code == 1

    def test_thresholds_auth_failure_json_error(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.performance.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "thresholds"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_thresholds_empty_returns_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_all_thresholds",
            return_value={"thresholds": []},
        )
        mocker.patch(
            "garmin_cli.commands.performance.serialize_thresholds",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "thresholds"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 0

    def test_thresholds_server_error_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_all_thresholds",
            side_effect=GarminCliError(error="Server error", error_code="SERVER_ERROR"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "thresholds"])
        assert result.exit_code == 1

    def test_thresholds_server_error_json_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_all_thresholds",
            side_effect=GarminCliError(error="Server error", error_code="SERVER_ERROR"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "thresholds"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "SERVER_ERROR"


# ---------------------------------------------------------------------------
# performance vo2max command
# ---------------------------------------------------------------------------

class TestPerformanceVo2maxCommand:

    def test_vo2max_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_vo2max",
            return_value={"vo2MaxValue": 52.0},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "performance", "vo2max", "--date", "2026-03-11"]
        )
        assert result.exit_code == 0

    def test_vo2max_json_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_vo2max",
            return_value={"vo2MaxValue": 52.0},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "performance", "vo2max", "--date", "2026-03-11"]
        )
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_vo2max_default_to_today(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mock_latest = mocker.patch(
            "garmin_cli.commands.performance.get_latest_vo2max",
            return_value=[{"generic": {"calendarDate": "2026-03-10", "vo2MaxValue": 52.0}}],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["--json", "performance", "vo2max"])
        mock_latest.assert_called_once_with()

    def test_vo2max_auth_failure_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.performance.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "vo2max"])
        assert result.exit_code == 1

    def test_vo2max_table_output_handles_list_payload(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_vo2max",
            return_value=[{"calendarDate": "2026-03-11", "vo2MaxValue": 52.0}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "vo2max", "--date", "2026-03-11"])
        assert result.exit_code == 0
        assert "2026-03-11" in result.output or "52.0" in result.output

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


# ---------------------------------------------------------------------------
# performance zones command
# ---------------------------------------------------------------------------

class TestPerformanceZonesCommand:

    def test_zones_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_lactate_threshold",
            return_value={"lactateThresholdHeartRate": 168},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "zones"])
        assert result.exit_code == 0

    def test_zones_json_ok(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_lactate_threshold",
            return_value={"lactateThresholdHeartRate": 168},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "zones"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_zones_auth_failure_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.performance.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "zones"])
        assert result.exit_code == 1

    def test_zones_table_output_handles_list_payload(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.performance.get_lactate_threshold",
            return_value=[{"sport": "running", "lactateThresholdHeartRate": 168}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "zones"])
        assert result.exit_code == 0
        assert "running" in result.output or "168" in result.output


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

    def test_garth_home_alias_still_passed_to_config(self, mocker: Any) -> None:
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
            ["--garth-home", "/compat/garth", "performance", "thresholds"],
        )
        assert mock_auth.called
        config = mock_auth.call_args[0][0]
        assert config.garth_home == "/compat/garth"
