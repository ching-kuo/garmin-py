"""CLI integration tests for new performance commands: race-predictions, endurance-score, hill-score."""
from __future__ import annotations

import json
from typing import Any

from click.testing import CliRunner

from garmin_cli.cli import cli


# ---------------------------------------------------------------------------
# performance race-predictions command
# ---------------------------------------------------------------------------

class TestPerformanceRacePredictionsCommand:

    def test_race_predictions_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_race_predictions", return_value={})
        mocker.patch("garmin_cli.commands.performance.serialize_race_predictions", return_value=[])
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["performance", "race-predictions"])
        mock_auth.assert_called_once()

    def test_race_predictions_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_race_predictions", return_value={})
        mocker.patch(
            "garmin_cli.commands.performance.serialize_race_predictions",
            return_value=[
                {"race_type": "5K", "predicted_time_seconds": 1500, "distance_meters": 5000},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "race-predictions"])
        assert result.exit_code == 0

    def test_race_predictions_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_race_predictions", return_value={})
        mocker.patch(
            "garmin_cli.commands.performance.serialize_race_predictions",
            return_value=[
                {"race_type": "5K", "predicted_time_seconds": 1500, "distance_meters": 5000},
                {"race_type": "10K", "predicted_time_seconds": 3200, "distance_meters": 10000},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "race-predictions"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_race_predictions_count_matches_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_race_predictions", return_value={})
        mocker.patch(
            "garmin_cli.commands.performance.serialize_race_predictions",
            return_value=[
                {"race_type": "5K", "predicted_time_seconds": 1500, "distance_meters": 5000},
                {"race_type": "10K", "predicted_time_seconds": 3200, "distance_meters": 10000},
                {"race_type": "HalfMarathon", "predicted_time_seconds": 7200, "distance_meters": 21097},
                {"race_type": "Marathon", "predicted_time_seconds": 15000, "distance_meters": 42195},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "race-predictions"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 4
        assert len(parsed["data"]) == 4

    def test_race_predictions_no_date_range_in_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_race_predictions", return_value={})
        mocker.patch("garmin_cli.commands.performance.serialize_race_predictions", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "race-predictions"])
        parsed = json.loads(result.output)
        assert parsed.get("date_range") is None

    def test_race_predictions_auth_failure_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.performance.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "race-predictions"])
        assert result.exit_code == 1

    def test_race_predictions_auth_failure_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.performance.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "race-predictions"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_race_predictions_table_output_not_json(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_race_predictions", return_value={})
        mocker.patch(
            "garmin_cli.commands.performance.serialize_race_predictions",
            return_value=[{"race_type": "5K", "predicted_time_seconds": 1500, "distance_meters": 5000}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "race-predictions"])
        assert result.exit_code == 0
        try:
            json.loads(result.output)
            is_json = True
        except (json.JSONDecodeError, ValueError):
            is_json = False
        assert not is_json


# ---------------------------------------------------------------------------
# performance endurance-score command
# ---------------------------------------------------------------------------

class TestPerformanceEnduranceScoreCommand:

    def test_endurance_score_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_endurance_score_range", return_value=[])
        mocker.patch("garmin_cli.commands.performance.serialize_endurance_score", return_value=[])
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["performance", "endurance-score", "--days", "1"])
        mock_auth.assert_called_once()

    def test_endurance_score_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_endurance_score_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.performance.serialize_endurance_score",
            return_value=[{
                "date": "2026-03-11",
                "overall_score": 42.5,
                "endurance_classification": "MODERATE",
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "endurance-score", "--days", "1"])
        assert result.exit_code == 0

    def test_endurance_score_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_endurance_score_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.performance.serialize_endurance_score",
            return_value=[{"date": "2026-03-11", "overall_score": 42.5, "endurance_classification": "MODERATE"}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "endurance-score", "--days", "1"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_endurance_score_date_range_in_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_endurance_score_range", return_value=[])
        mocker.patch("garmin_cli.commands.performance.serialize_endurance_score", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "performance", "endurance-score", "--from", "2026-03-01", "--to", "2026-03-07"]
        )
        parsed = json.loads(result.output)
        assert parsed["date_range"] is not None
        assert parsed["date_range"]["from"] == "2026-03-01"
        assert parsed["date_range"]["to"] == "2026-03-07"

    def test_endurance_score_conflict_fails(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "endurance-score", "--date", "2026-03-11", "--days", "7"])
        assert result.exit_code != 0

    def test_endurance_score_auth_failure_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.performance.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "endurance-score", "--days", "1"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_endurance_score_empty_data_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_endurance_score_range", return_value=[])
        mocker.patch("garmin_cli.commands.performance.serialize_endurance_score", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "endurance-score", "--days", "1"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 0


# ---------------------------------------------------------------------------
# performance hill-score command
# ---------------------------------------------------------------------------

class TestPerformanceHillScoreCommand:

    def test_hill_score_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_hill_score_range", return_value=[])
        mocker.patch("garmin_cli.commands.performance.serialize_hill_score", return_value=[])
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["performance", "hill-score", "--days", "1"])
        mock_auth.assert_called_once()

    def test_hill_score_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_hill_score_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.performance.serialize_hill_score",
            return_value=[{
                "date": "2026-03-11",
                "overall_score": 38.0,
                "endurance_score": 40.0,
                "strength_score": 36.0,
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "hill-score", "--days", "1"])
        assert result.exit_code == 0

    def test_hill_score_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_hill_score_range", return_value=[])
        mocker.patch(
            "garmin_cli.commands.performance.serialize_hill_score",
            return_value=[{"date": "2026-03-11", "overall_score": 38.0, "endurance_score": 40.0, "strength_score": 36.0}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "hill-score", "--days", "1"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_hill_score_date_range_in_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_hill_score_range", return_value=[])
        mocker.patch("garmin_cli.commands.performance.serialize_hill_score", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "performance", "hill-score", "--from", "2026-03-01", "--to", "2026-03-07"]
        )
        parsed = json.loads(result.output)
        assert parsed["date_range"] is not None
        assert parsed["date_range"]["from"] == "2026-03-01"
        assert parsed["date_range"]["to"] == "2026-03-07"

    def test_hill_score_conflict_fails(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["performance", "hill-score", "--date", "2026-03-11", "--days", "7"])
        assert result.exit_code != 0

    def test_hill_score_auth_failure_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.performance.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "hill-score", "--days", "1"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_hill_score_empty_data_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.performance.ensure_authenticated")
        mocker.patch("garmin_cli.commands.performance.get_hill_score_range", return_value=[])
        mocker.patch("garmin_cli.commands.performance.serialize_hill_score", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "performance", "hill-score", "--days", "1"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 0
