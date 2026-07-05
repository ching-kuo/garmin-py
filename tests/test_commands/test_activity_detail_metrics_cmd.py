"""CLI integration tests for activity detail-metrics command."""
from __future__ import annotations

import json
from typing import Any

from click.testing import CliRunner

from garmin_cli.cli import cli

_DETAILS = {
    "metricDescriptors": [
        {"key": "directTimestamp", "unit": None, "metricsIndex": 0},
        {"key": "directHeartRate", "unit": {"key": "bpm"}, "metricsIndex": 1},
    ],
    "activityDetailMetrics": [
        {"metrics": [1000, 120]},
        {"metrics": [2000, 130]},
    ],
}


class TestActivityDetailMetricsCommand:

    def test_detail_metrics_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value=_DETAILS,
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["activity", "detail-metrics", "12345678"])
        mock_auth.assert_called_once()

    def test_detail_metrics_json_rows(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value=_DETAILS,
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "detail-metrics", "12345678"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert parsed["count"] == 2
        assert parsed["data"][0] == {"directTimestamp": 1000, "directHeartRate": 120}

    def test_detail_metrics_metric_filter(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value=_DETAILS,
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "activity", "detail-metrics", "12345678", "--metric", "directHeartRate"],
        )
        parsed = json.loads(result.output)
        assert parsed["data"] == [{"directHeartRate": 120}, {"directHeartRate": 130}]

    def test_detail_metrics_unknown_metric_error_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value=_DETAILS,
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "activity", "detail-metrics", "12345678", "--metric", "nope"],
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_INPUT"

    def test_detail_metrics_empty_stream_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            return_value={},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "detail-metrics", "12345678"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 0
        assert parsed["data"] == []

    def test_detail_metrics_not_found_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_details",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "detail-metrics", "99999999"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "NOT_FOUND"
