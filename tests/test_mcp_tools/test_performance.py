"""Performance MCP tool tests (moved from test_mcp_server.py; assertions unchanged)."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.endpoints import metrics as metrics_endpoints  # noqa: E402
from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.helpers import make_http_error as _http_error  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


class TestMetricsEndpoints:
    """Verify metrics endpoint helpers call Garmin APIs correctly."""


    def test_get_race_predictions(self, mocker: Any) -> None:
        # The bare /metrics-service/metrics/racepredictions path 404s; the
        # typed get_race_predictions method scopes the same endpoint under
        # the account displayName and returns one flat dict (time5K, ...)
        # rather than a list of per-race objects.
        mock_garth = MagicMock()
        mock_garth.get_race_predictions.return_value = {
            "calendarDate": "2026-01-01",
            "time5K": 1500,
        }
        mocker.patch("garmin_cli.endpoints.metrics.garth", mock_garth)

        result = metrics_endpoints.get_race_predictions()
        assert result["time5K"] == 1500
        mock_garth.get_race_predictions.assert_called_once_with()
        mock_garth.connectapi.assert_not_called()

    def test_get_race_predictions_coalesces_none(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_race_predictions.return_value = None
        mocker.patch("garmin_cli.endpoints.metrics.garth", mock_garth)

        result = metrics_endpoints.get_race_predictions()
        assert result == []

    def test_get_endurance_score(self, mocker: Any) -> None:
        mock_request = mocker.patch(
            "garmin_cli.endpoints.metrics._request",
            return_value={"calendarDate": "2026-01-01", "overallScore": 5100},
        )
        result = metrics_endpoints.get_endurance_score(date(2026, 1, 1))
        assert result["overallScore"] == 5100
        mock_request.assert_called_once_with(
            "/metrics-service/metrics/endurancescore",
            params={"calendarDate": "2026-01-01"},
        )

    def test_get_endurance_score_coalesces_none(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.endpoints.metrics._request", return_value=None)
        result = metrics_endpoints.get_endurance_score(date(2026, 1, 1))
        assert result == {}

    def test_get_endurance_score_range(self, mocker: Any) -> None:
        mock_collect = mocker.patch(
            "garmin_cli.endpoints.metrics._collect_daily_range",
            return_value=[{"calendarDate": "2026-01-01", "overallScore": 5100}],
        )
        result = metrics_endpoints.get_endurance_score_range(
            date(2026, 1, 1),
            date(2026, 1, 3),
        )
        assert result[0]["overallScore"] == 5100
        mock_collect.assert_called_once_with(
            metrics_endpoints.get_endurance_score,
            date(2026, 1, 1),
            date(2026, 1, 3),
        )

    def test_get_hill_score(self, mocker: Any) -> None:
        mock_request = mocker.patch(
            "garmin_cli.endpoints.metrics._request",
            return_value={"calendarDate": "2026-01-01", "overallScore": 42},
        )
        result = metrics_endpoints.get_hill_score(date(2026, 1, 1))
        assert result["overallScore"] == 42
        mock_request.assert_called_once_with(
            "/metrics-service/metrics/hillscore",
            params={"calendarDate": "2026-01-01"},
        )

    def test_get_hill_score_coalesces_none(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.endpoints.metrics._request", return_value=None)
        result = metrics_endpoints.get_hill_score(date(2026, 1, 1))
        assert result == {}

    def test_get_hill_score_range(self, mocker: Any) -> None:
        mock_collect = mocker.patch(
            "garmin_cli.endpoints.metrics._collect_daily_range",
            return_value=[{"calendarDate": "2026-01-01", "overallScore": 42}],
        )
        result = metrics_endpoints.get_hill_score_range(
            date(2026, 1, 1),
            date(2026, 1, 3),
        )
        assert result[0]["overallScore"] == 42
        mock_collect.assert_called_once_with(
            metrics_endpoints.get_hill_score,
            date(2026, 1, 1),
            date(2026, 1, 3),
        )

    def test_get_race_predictions_not_found(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_race_predictions.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.metrics.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            metrics_endpoints.get_race_predictions()
        assert exc_info.value.error_code == "NOT_FOUND"


class TestPerformanceTools:

    def test_performance_race_predictions(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        # Live flat-dict shape, so the MCP tool path exercises the reshape gate.
        mocker.patch(
            "garmin_cli.mcp_tools.performance.get_race_predictions",
            return_value={
                "calendarDate": "2026-07-01",
                "time5K": 1293,
                "time10K": 2701,
                "timeHalfMarathon": 6004,
                "timeMarathon": 12600,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "performance_race_predictions", {})
        assert result["count"] == 4
        rows = {row["race_type"]: row for row in result["rows"]}
        assert rows["Marathon"]["predicted_time_seconds"] == 12600
        assert rows["5K"]["distance_meters"] == 5000

    def test_performance_endurance_score(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.performance.get_endurance_score_range",
            return_value=[{"calendarDate": "2026-01-01", "overallScore": 5100}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "performance_endurance_score", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
        assert result["count"] == 1
        assert result["rows"][0]["overall_score"] == 5100

    def test_performance_hill_score(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.performance.get_hill_score_range",
            return_value=[{"calendarDate": "2026-01-01", "overallScore": 42}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "performance_hill_score", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
        assert result["count"] == 1
        assert result["rows"][0]["overall_score"] == 42

    def test_performance_thresholds(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.performance.get_all_thresholds", return_value={"thresholds": [{"sport": "running", "lactateThresholdHeartRate": 168}]})
        server = create_mcp_server(_config())
        result = _call(server, "performance_thresholds", {})
        assert result["count"] == 1

    def test_performance_vo2max_with_date(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.performance.get_vo2max", return_value=[{"calendarDate": "2026-01-01", "generic": {"vo2MaxValue": 48, "calendarDate": "2026-01-01"}}])
        server = create_mcp_server(_config())
        result = _call(server, "performance_vo2max", {"date": "2026-01-01"})
        assert result["count"] >= 1

    def test_performance_vo2max_latest(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.performance.get_latest_vo2max", return_value=[
            {"generic": {"vo2MaxValue": 48, "calendarDate": "2026-01-01"}},
            {"generic": {"vo2MaxValue": 49, "calendarDate": "2026-01-05"}},
        ])
        server = create_mcp_server(_config())
        result = _call(server, "performance_vo2max", {})
        # Should filter to latest date only
        assert all(row["date"] == "2026-01-05" for row in result["rows"])

    def test_performance_zones(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.performance.get_lactate_threshold", return_value=[{"sport": "running", "lactateThresholdHeartRate": 168}])
        server = create_mcp_server(_config())
        result = _call(server, "performance_zones", {})
        assert result["count"] >= 1
