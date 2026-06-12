"""CLI integration tests for new health commands: steps, daily-summary, intensity-minutes."""
from __future__ import annotations

import json
from typing import Any

from click.testing import CliRunner

from garmin_cli.cli import cli


# ---------------------------------------------------------------------------
# health steps command
# ---------------------------------------------------------------------------

class TestHealthStepsCommand:

    def test_steps_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_steps_range", return_value=[])
        mocker.patch("garmin_cli.commands.health.serialize_steps", return_value=[])
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["health", "steps", "--days", "1"])
        mock_auth.assert_called_once()

    def test_steps_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_steps_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.health.serialize_steps",
            return_value=[{"date": "2026-03-11", "total_steps": 9500, "total_distance": 7200, "step_goal": 10000}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "steps", "--days", "1"])
        assert result.exit_code == 0

    def test_steps_json_envelope_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_steps_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.health.serialize_steps",
            return_value=[{"date": "2026-03-11", "total_steps": 9500, "total_distance": 7200, "step_goal": 10000}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "steps", "--days", "1"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_steps_count_matches_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_steps_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.health.serialize_steps",
            return_value=[
                {"date": "2026-03-10", "total_steps": 8000, "total_distance": 6000, "step_goal": 10000},
                {"date": "2026-03-11", "total_steps": 9500, "total_distance": 7200, "step_goal": 10000},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "steps", "--days", "2"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 2
        assert len(parsed["data"]) == 2

    def test_steps_date_range_in_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_steps_range", return_value=[])
        mocker.patch("garmin_cli.commands.health.serialize_steps", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "steps", "--from", "2026-03-01", "--to", "2026-03-07"])
        parsed = json.loads(result.output)
        assert parsed["date_range"] is not None
        assert parsed["date_range"]["from"] == "2026-03-01"
        assert parsed["date_range"]["to"] == "2026-03-07"

    def test_steps_conflict_date_and_days_fails(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "steps", "--date", "2026-03-11", "--days", "7"])
        assert result.exit_code != 0

    def test_steps_auth_failure_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.health.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "steps", "--days", "1"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_steps_empty_data_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_steps_range", return_value=[])
        mocker.patch("garmin_cli.commands.health.serialize_steps", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "steps", "--days", "1"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 0


# ---------------------------------------------------------------------------
# health daily-summary command
# ---------------------------------------------------------------------------

class TestHealthDailySummaryCommand:

    def test_daily_summary_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_daily_summary_range", return_value=[])
        mocker.patch("garmin_cli.commands.health.serialize_daily_summary", return_value=[])
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["health", "daily-summary", "--days", "1"])
        mock_auth.assert_called_once()

    def test_daily_summary_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_daily_summary_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.health.serialize_daily_summary",
            return_value=[{
                "date": "2026-03-11",
                "total_steps": 8500,
                "distance_km": 6.5,
                "active_kilocalories": 450,
                "floors_ascended": 5,
                "floors_descended": 4,
                "moderate_intensity_minutes": 30,
                "vigorous_intensity_minutes": 15,
                "resting_heart_rate": 58,
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "daily-summary", "--days", "1"])
        assert result.exit_code == 0

    def test_daily_summary_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_daily_summary_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.health.serialize_daily_summary",
            return_value=[{"date": "2026-03-11", "total_steps": 8500}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "daily-summary", "--days", "1"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_daily_summary_count_matches_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_daily_summary_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.health.serialize_daily_summary",
            return_value=[
                {"date": "2026-03-10", "total_steps": 7000},
                {"date": "2026-03-11", "total_steps": 8500},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "daily-summary", "--days", "2"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 2

    def test_daily_summary_date_range_in_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_daily_summary_range", return_value=[])
        mocker.patch("garmin_cli.commands.health.serialize_daily_summary", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "daily-summary", "--from", "2026-03-01", "--to", "2026-03-07"])
        parsed = json.loads(result.output)
        assert parsed["date_range"] is not None

    def test_daily_summary_conflict_fails(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "daily-summary", "--date", "2026-03-11", "--days", "7"])
        assert result.exit_code != 0

    def test_daily_summary_auth_failure_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.health.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "daily-summary", "--days", "1"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_daily_summary_empty_data_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_daily_summary_range", return_value=[])
        mocker.patch("garmin_cli.commands.health.serialize_daily_summary", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "daily-summary", "--days", "1"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 0


# ---------------------------------------------------------------------------
# health intensity-minutes command
# ---------------------------------------------------------------------------

class TestHealthIntensityMinutesCommand:

    def test_intensity_minutes_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_intensity_minutes_range", return_value=[])
        mocker.patch("garmin_cli.commands.health.serialize_intensity_minutes", return_value=[])
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["health", "intensity-minutes", "--days", "1"])
        mock_auth.assert_called_once()

    def test_intensity_minutes_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_intensity_minutes_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.health.serialize_intensity_minutes",
            return_value=[{
                "date": "2026-03-11",
                "moderate_value": 30,
                "vigorous_value": 15,
                "weekly_goal": 150,
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "intensity-minutes", "--days", "1"])
        assert result.exit_code == 0

    def test_intensity_minutes_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_intensity_minutes_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.health.serialize_intensity_minutes",
            return_value=[{"date": "2026-03-11", "moderate_value": 30, "vigorous_value": 15, "weekly_goal": 150}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "intensity-minutes", "--days", "1"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_intensity_minutes_date_range_in_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        mocker.patch("garmin_cli.commands.health.get_intensity_minutes_range", return_value=[])
        mocker.patch("garmin_cli.commands.health.serialize_intensity_minutes", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "health", "intensity-minutes", "--from", "2026-03-01", "--to", "2026-03-07"]
        )
        parsed = json.loads(result.output)
        assert parsed["date_range"] is not None
        assert parsed["date_range"]["from"] == "2026-03-01"
        assert parsed["date_range"]["to"] == "2026-03-07"

    def test_intensity_minutes_conflict_fails(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.health.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["health", "intensity-minutes", "--date", "2026-03-11", "--days", "7"])
        assert result.exit_code != 0

    def test_intensity_minutes_auth_failure_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.health.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "health", "intensity-minutes", "--days", "1"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"
