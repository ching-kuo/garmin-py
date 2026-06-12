"""CLI integration tests for activity metrics-describe command."""
from __future__ import annotations

import json
from typing import Any

from click.testing import CliRunner

from garmin_cli.cli import cli


# ---------------------------------------------------------------------------
# activity metrics-describe command
# ---------------------------------------------------------------------------

class TestActivityMetricsDescribeCommand:

    def test_metrics_describe_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value={"metricDescriptors": []},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_metrics_descriptors",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["activity", "metrics-describe", "12345678"])
        mock_auth.assert_called_once()

    def test_metrics_describe_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value={"metricDescriptors": []},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_metrics_descriptors",
            return_value=[
                {"key": "directSpeed", "unit": "mps", "metricsIndex": 0},
                {"key": "heartRate", "unit": "bpm", "metricsIndex": 1},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "metrics-describe", "12345678"])
        assert result.exit_code == 0

    def test_metrics_describe_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value={"metricDescriptors": []},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_metrics_descriptors",
            return_value=[{"key": "heartRate", "unit": "bpm", "metricsIndex": 0}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "metrics-describe", "12345678"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_metrics_describe_count_matches_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value={"metricDescriptors": []},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_metrics_descriptors",
            return_value=[
                {"key": "directSpeed", "unit": "mps", "metricsIndex": 0},
                {"key": "heartRate", "unit": "bpm", "metricsIndex": 1},
                {"key": "directPower", "unit": "watt", "metricsIndex": 2},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "metrics-describe", "12345678"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 3
        assert len(parsed["data"]) == 3

    def test_metrics_describe_data_has_expected_keys(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value={"metricDescriptors": []},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_metrics_descriptors",
            return_value=[{"key": "heartRate", "unit": "bpm", "metricsIndex": 1}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "metrics-describe", "12345678"])
        parsed = json.loads(result.output)
        row = parsed["data"][0]
        assert "key" in row
        assert "unit" in row
        assert "metricsIndex" in row

    def test_metrics_describe_no_date_range_in_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value={"metricDescriptors": []},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_metrics_descriptors",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "metrics-describe", "12345678"])
        parsed = json.loads(result.output)
        assert parsed.get("date_range") is None

    def test_metrics_describe_empty_descriptors_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value={"metricDescriptors": []},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_metrics_descriptors",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "metrics-describe", "12345678"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 0
        assert parsed["data"] == []

    def test_metrics_describe_auth_failure_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.activities.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "metrics-describe", "12345678"])
        assert result.exit_code == 1

    def test_metrics_describe_auth_failure_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.activities.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "metrics-describe", "12345678"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_metrics_describe_not_found_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "metrics-describe", "99999999"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "NOT_FOUND"

    def test_metrics_describe_table_output_not_json(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value={"metricDescriptors": []},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_metrics_descriptors",
            return_value=[{"key": "heartRate", "unit": "bpm", "metricsIndex": 1}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "metrics-describe", "12345678"])
        assert result.exit_code == 0
        try:
            json.loads(result.output)
            is_json = True
        except (json.JSONDecodeError, ValueError):
            is_json = False
        assert not is_json
