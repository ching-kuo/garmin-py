"""Health MCP tool tests (moved from test_mcp_server.py; assertions unchanged)."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.endpoints import health as health_endpoints  # noqa: E402
from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.helpers import make_http_error as _http_error  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


class TestHealthEndpoints:
    """Verify new health endpoint helpers call Garmin APIs correctly."""

    def test_get_daily_summary(self, mocker: Any) -> None:
        mock_request = mocker.patch(
            "garmin_cli.endpoints.health._request",
            return_value={"calendarDate": "2026-01-01", "totalSteps": 12345},
        )
        result = health_endpoints.get_daily_summary(date(2026, 1, 1))
        assert result["totalSteps"] == 12345
        mock_request.assert_called_once_with(
            "/usersummary-service/usersummary/daily/",
            params={"calendarDate": "2026-01-01"},
        )

    def test_get_daily_summary_coalesces_none(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.endpoints.health._request", return_value=None)
        result = health_endpoints.get_daily_summary(date(2026, 1, 1))
        assert result == {}

    def test_get_daily_summary_range(self, mocker: Any) -> None:
        mock_collect = mocker.patch(
            "garmin_cli.endpoints.health._collect_daily_range",
            return_value=[{"calendarDate": "2026-01-01"}],
        )
        result = health_endpoints.get_daily_summary_range(
            date(2026, 1, 1),
            date(2026, 1, 3),
        )
        assert result == [{"calendarDate": "2026-01-01"}]
        mock_collect.assert_called_once_with(
            health_endpoints.get_daily_summary,
            date(2026, 1, 1),
            date(2026, 1, 3),
        )

    def test_get_steps_range(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.health._request",
            return_value=[{"calendarDate": "2026-01-01", "totalSteps": 12345}],
        )
        result = health_endpoints.get_steps_range(date(2026, 1, 1), date(2026, 1, 7))
        assert result[0]["totalSteps"] == 12345

    def test_get_steps_range_wraps_dict_as_list(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.health._request",
            return_value={"calendarDate": "2026-01-01", "totalSteps": 99},
        )
        result = health_endpoints.get_steps_range(date(2026, 1, 1), date(2026, 1, 1))
        assert result == [{"calendarDate": "2026-01-01", "totalSteps": 99}]

    def test_get_steps_range_coalesces_none(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.endpoints.health._request", return_value=None)
        result = health_endpoints.get_steps_range(date(2026, 1, 1), date(2026, 1, 7))
        assert result == []

    def test_get_intensity_minutes_range(self, mocker: Any) -> None:
        mock_request = mocker.patch(
            "garmin_cli.endpoints.health._request",
            return_value=[{"calendarDate": "2026-01-01", "moderateValue": 30}],
        )
        result = health_endpoints.get_intensity_minutes_range(
            date(2026, 1, 1),
            date(2026, 1, 7),
        )
        assert result[0]["moderateValue"] == 30
        mock_request.assert_called_once_with(
            "/usersummary-service/stats/im/daily/2026-01-01/2026-01-07"
        )

    def test_get_intensity_minutes_range_coalesces_none(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.endpoints.health._request", return_value=None)
        result = health_endpoints.get_intensity_minutes_range(
            date(2026, 1, 1),
            date(2026, 1, 7),
        )
        assert result == []

    def test_get_steps_range_not_found(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.health._request",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        with pytest.raises(GarminCliError, match="Not found"):
            health_endpoints.get_steps_range(date(2026, 1, 1), date(2026, 1, 7))

    def test_get_resting_hr_uses_displayname_scoped_typed_method(self, mocker: Any) -> None:
        # The bare /wellness-service/wellness/dailyHeartRate/{day} path 403s;
        # the typed get_heart_rates method scopes the same endpoint under the
        # account displayName.
        mock_garth = MagicMock()
        mock_garth.get_heart_rates.return_value = {
            "calendarDate": "2026-01-01",
            "restingHeartRate": 45,
        }
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        result = health_endpoints.get_resting_hr(date(2026, 1, 1))
        assert result["restingHeartRate"] == 45
        mock_garth.get_heart_rates.assert_called_once_with("2026-01-01")
        mock_garth.connectapi.assert_not_called()

    def test_get_resting_hr_not_found(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_heart_rates.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            health_endpoints.get_resting_hr(date(2026, 1, 1))
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_get_resting_hr_forbidden_maps_to_auth_failed(self, mocker: Any) -> None:
        # Mirrors the live drift symptom that motivated the typed-method fix:
        # the retired bare path returned 403 ForbiddenException.
        mock_garth = MagicMock()
        mock_garth.get_heart_rates.side_effect = _http_error(403)
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            health_endpoints.get_resting_hr(date(2026, 1, 1))
        assert exc_info.value.error_code == "AUTH_FAILED"


class TestHealthTools:
    """Verify health tools call endpoints and return envelope."""

    def test_health_daily_summary(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.health.get_daily_summary_range",
            return_value=[
                {
                    "calendarDate": "2026-01-01",
                    "totalSteps": 12345,
                    "totalDistanceMeters": 7500,
                }
            ],
        )
        server = create_mcp_server(_config())
        result = _call(server, "health_daily_summary", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["total_steps"] == 12345

    def test_health_steps(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.health.get_steps_range",
            return_value=[{"calendarDate": "2026-01-01", "totalSteps": 12345, "stepGoal": 10000}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "health_steps", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
        assert result["count"] == 1
        assert result["rows"][0]["step_goal"] == 10000

    def test_health_intensity_minutes(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.health.get_intensity_minutes_range",
            return_value=[{"calendarDate": "2026-01-01", "moderateValue": 45, "vigorousValue": 15}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "health_intensity_minutes", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
        assert result["count"] == 1
        assert result["rows"][0]["moderate_value"] == 45

    def test_health_sleep(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_sleep", return_value=[{"dailySleepDTO": {"calendarDate": "2026-01-01", "sleepTimeSeconds": 28800}}])
        server = create_mcp_server(_config())
        result = _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["date"] == "2026-01-01"

    def test_health_hrv(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_hrv", return_value={"hrvSummaries": [{"calendarDate": "2026-01-01", "weeklyAvg": 45, "lastNightAvg": 42, "status": "BALANCED"}]})
        server = create_mcp_server(_config())
        result = _call(server, "health_hrv", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["weekly_avg"] == 45

    def test_health_weight(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_weight", return_value={"dateWeightList": [{"calendarDate": "2026-01-01", "weight": 75000, "bmi": 23.5, "bodyFat": 15.0}]})
        server = create_mcp_server(_config())
        result = _call(server, "health_weight", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["weight_kg"] == 75.0

    def test_health_body_battery(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_body_battery_range", return_value=[{"calendarDate": "2026-01-01", "bodyBatteryValuesArray": [[1735689600, 80], [1735775999, 30]]}])
        server = create_mcp_server(_config())
        result = _call(server, "health_body_battery", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1

    def test_health_stress(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_stress_range", return_value=[{"calendarDate": "2026-01-01", "avgStressLevel": 35, "maxStressLevel": 70}])
        server = create_mcp_server(_config())
        result = _call(server, "health_stress", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["avg_stress"] == 35

    def test_health_spo2(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_spo2_range", return_value=[{"dateTime": "2026-01-01", "averageSpO2": 97, "lowestSpO2": 94}])
        server = create_mcp_server(_config())
        result = _call(server, "health_spo2", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["avg_spo2"] == 97

    def test_health_resting_hr(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_resting_hr_range", return_value=[{"calendarDate": "2026-01-01", "restingHeartRateValue": 55}])
        server = create_mcp_server(_config())
        result = _call(server, "health_resting_hr", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["resting_hr"] == 55

    def test_health_readiness(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_training_readiness_range", return_value=[{"calendarDate": "2026-01-01", "score": 75, "level": "MODERATE"}])
        server = create_mcp_server(_config())
        result = _call(server, "health_readiness", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["score"] == 75

    def test_health_training_status(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_training_status", return_value={"calendarDate": "2026-01-01", "trainingStatusType": "PRODUCTIVE", "trainingLoadType": "OPTIMAL"})
        server = create_mcp_server(_config())
        result = _call(server, "health_training_status", {"date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["training_status"] == "PRODUCTIVE"
