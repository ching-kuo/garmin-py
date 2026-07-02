"""Tests for the MCP server module (TDD -- written before implementation)."""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli import serializers as garmin_serializers  # noqa: E402
from garmin_cli.config import CliConfig  # noqa: E402
from garmin_cli.endpoints import devices as devices_endpoints  # noqa: E402
from garmin_cli.endpoints import health as health_endpoints  # noqa: E402
from garmin_cli.endpoints import metrics as metrics_endpoints  # noqa: E402
from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.helpers import make_http_error as _http_error  # noqa: E402


def _config(**overrides: Any) -> CliConfig:
    defaults = {"email": "test@example.com", "password": "test_password", "garth_home": "/tmp/garth"}
    defaults.update(overrides)
    return CliConfig(**defaults)


def _call(mcp_server: Any, tool_name: str, args: dict[str, Any] | None = None) -> Any:
    """Call an MCP tool and parse the JSON text result."""
    result = asyncio.run(mcp_server.call_tool(tool_name, args or {}))
    # MCPServer may return (list[Content], dict) tuple or list[Content]
    if isinstance(result, tuple):
        content_list = result[0]
    else:
        content_list = result
    return json.loads(content_list[0].text)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

class TestToolRegistration:
    """Verify all expected tools are registered."""

    EXPECTED_TOOLS = frozenset({
        "health_sleep",
        "health_hrv",
        "health_weight",
        "health_daily_summary",
        "health_steps",
        "health_intensity_minutes",
        "health_body_battery",
        "health_stress",
        "health_spo2",
        "health_resting_hr",
        "health_readiness",
        "health_training_status",
        "activity_list",
        "activity_get",
        "activity_weather",
        "activity_laps",
        "activity_hr_zones",
        "activity_metrics_describe",
        "workout_list",
        "workout_get",
        "workout_calendar",
        "workout_create",
        "workout_schedule",
        "workout_update",
        "workout_delete",
        "performance_thresholds",
        "performance_race_predictions",
        "performance_endurance_score",
        "performance_hill_score",
        "performance_vo2max",
        "performance_zones",
        "device_list",
        "login_status",
        "report_snapshot",
    })

    def test_all_tools_registered(self) -> None:
        server = create_mcp_server(_config())
        tools = asyncio.run(server.list_tools())
        tool_names = {t.name for t in tools}
        assert tool_names == self.EXPECTED_TOOLS


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    """Verify input validation raises ToolError."""

    def _server(self) -> Any:
        return create_mcp_server(_config())

    def test_invalid_date_format(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="Invalid date format"):
            _call(server, "health_sleep", {"start_date": "not-a-date", "end_date": "2026-01-07"})

    def test_date_range_exceeds_90_days(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="90 days"):
            _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-06-01"})

    def test_start_after_end(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="must be on or before"):
            _call(server, "health_sleep", {"start_date": "2026-03-10", "end_date": "2026-03-01"})

    def test_negative_limit(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="limit"):
            _call(server, "activity_list", {"limit": 0})

    def test_limit_over_100(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="limit"):
            _call(server, "activity_list", {"limit": 101})

    def test_negative_activity_id(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_get", {"activity_id": -1})

    def test_zero_activity_id(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_get", {"activity_id": 0})

    def test_negative_start_offset(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="start"):
            _call(server, "activity_list", {"start": -1})


# ---------------------------------------------------------------------------
# Endpoint layer -- health additions
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Endpoint layer -- metrics
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Endpoint layer -- devices
# ---------------------------------------------------------------------------

class TestDeviceEndpoints:
    """Verify device endpoint helpers call Garmin APIs correctly."""


    def test_get_devices(self, mocker: Any) -> None:
        mock_request = mocker.patch(
            "garmin_cli.endpoints.devices._request",
            return_value=[{"deviceId": 1, "displayName": "Forerunner"}],
        )
        result = devices_endpoints.get_devices()
        assert result[0]["displayName"] == "Forerunner"
        mock_request.assert_called_once_with("/device-service/deviceregistration/devices")

    def test_get_devices_coalesces_none(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.endpoints.devices._request", return_value=None)
        result = devices_endpoints.get_devices()
        assert result == []

    def test_get_devices_not_found(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.devices._request",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        with pytest.raises(GarminCliError, match="Not found"):
            devices_endpoints.get_devices()


# ---------------------------------------------------------------------------
# Serializers -- new tool payloads
# ---------------------------------------------------------------------------

class TestNewSerializers:
    """Verify serializers for new MCP tool payloads."""

    def test_serialize_daily_summary(self) -> None:
        result = garmin_serializers.serialize_daily_summary(
            {
                "calendarDate": "2026-01-01",
                "totalSteps": 12345,
                "totalDistanceMeters": 7500,
                "activeKilocalories": 500,
                "floorsAscended": 10,
                "floorsDescended": 8,
                "moderateIntensityMinutes": 30,
                "vigorousIntensityMinutes": 12,
                "restingHeartRate": 48,
            }
        )
        assert result == [
            {
                "date": "2026-01-01",
                "total_steps": 12345,
                "distance_km": 7.5,
                "active_kilocalories": 500,
                "floors_ascended": 10,
                "floors_descended": 8,
                "moderate_intensity_minutes": 30,
                "vigorous_intensity_minutes": 12,
                "resting_heart_rate": 48,
            }
        ]

    def test_serialize_daily_summary_missing_fields(self) -> None:
        result = garmin_serializers.serialize_daily_summary({"calendarDate": "2026-01-01"})
        assert result == [
            {
                "date": "2026-01-01",
                "total_steps": None,
                "distance_km": None,
                "active_kilocalories": None,
                "floors_ascended": None,
                "floors_descended": None,
                "moderate_intensity_minutes": None,
                "vigorous_intensity_minutes": None,
                "resting_heart_rate": None,
            }
        ]

    def test_serialize_steps(self) -> None:
        result = garmin_serializers.serialize_steps(
            [{"calendarDate": "2026-01-01", "totalSteps": 12345, "totalDistance": 8100, "stepGoal": 10000}]
        )
        assert result == [
            {
                "date": "2026-01-01",
                "total_steps": 12345,
                "total_distance": 8100,
                "step_goal": 10000,
            }
        ]

    def test_serialize_intensity_minutes(self) -> None:
        result = garmin_serializers.serialize_intensity_minutes(
            [{"calendarDate": "2026-01-01", "moderateValue": 45, "vigorousValue": 15, "weeklyGoal": 150}]
        )
        assert result == [
            {
                "date": "2026-01-01",
                "moderate_value": 45,
                "vigorous_value": 15,
                "weekly_goal": 150,
            }
        ]

    def test_serialize_race_predictions(self) -> None:
        result = garmin_serializers.serialize_race_predictions(
            [{"raceType": "MARATHON", "predictedTimeInSeconds": 12600, "distanceMeters": 42195}]
        )
        assert result == [
            {
                "race_type": "MARATHON",
                "predicted_time_seconds": 12600,
                "distance_meters": 42195,
            }
        ]

    def test_serialize_race_predictions_reshapes_displayname_scoped_flat_dict(self) -> None:
        # The displayName-scoped endpoint returns one flat dict keyed by
        # race distance rather than a list of per-race objects.
        result = garmin_serializers.serialize_race_predictions(
            {
                "userId": 1,
                "calendarDate": "2026-01-01",
                "time5K": 1293,
                "time10K": 2737,
                "timeHalfMarathon": 6212,
                "timeMarathon": 13981,
            }
        )
        assert result == [
            {"race_type": "5K", "predicted_time_seconds": 1293, "distance_meters": 5000.0},
            {"race_type": "10K", "predicted_time_seconds": 2737, "distance_meters": 10000.0},
            {
                "race_type": "Half Marathon",
                "predicted_time_seconds": 6212,
                "distance_meters": 21097.5,
            },
            {
                "race_type": "Marathon",
                "predicted_time_seconds": 13981,
                "distance_meters": 42195.0,
            },
        ]

    def test_serialize_endurance_score(self) -> None:
        result = garmin_serializers.serialize_endurance_score(
            {
                "calendarDate": "2026-01-01",
                "overallScore": 5100,
                "enduranceClassification": "EXCELLENT",
            }
        )
        assert result == [
            {
                "date": "2026-01-01",
                "overall_score": 5100,
                "endurance_classification": "EXCELLENT",
            }
        ]

    def test_serialize_hill_score(self) -> None:
        result = garmin_serializers.serialize_hill_score(
            {
                "calendarDate": "2026-01-01",
                "overallScore": 42,
                "enduranceScore": 40,
                "strengthScore": 44,
            }
        )
        assert result == [
            {
                "date": "2026-01-01",
                "overall_score": 42,
                "endurance_score": 40,
                "strength_score": 44,
            }
        ]

    def test_serialize_device(self) -> None:
        result = garmin_serializers.serialize_device(
            {
                "deviceId": 1,
                "displayName": "Forerunner",
                "deviceTypeName": "WATCH",
                "lastSyncTime": "2026-01-01T10:00:00",
            }
        )
        assert result == [
            {
                "device_id": 1,
                "display_name": "Forerunner",
                "device_type": "WATCH",
                "last_sync_time": "2026-01-01T10:00:00",
            }
        ]

    def test_new_serializers_return_empty_list_for_none(self) -> None:
        assert garmin_serializers.serialize_daily_summary(None) == []
        assert garmin_serializers.serialize_steps(None) == []
        assert garmin_serializers.serialize_intensity_minutes(None) == []
        assert garmin_serializers.serialize_race_predictions(None) == []
        assert garmin_serializers.serialize_endurance_score(None) == []
        assert garmin_serializers.serialize_hill_score(None) == []
        assert garmin_serializers.serialize_device(None) == []


# ---------------------------------------------------------------------------
# Happy path -- health tools
# ---------------------------------------------------------------------------

class TestHealthTools:
    """Verify health tools call endpoints and return envelope."""

    def test_health_daily_summary(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_daily_summary_range",
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

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_steps_range",
            return_value=[{"calendarDate": "2026-01-01", "totalSteps": 12345, "stepGoal": 10000}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "health_steps", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
        assert result["count"] == 1
        assert result["rows"][0]["step_goal"] == 10000

    def test_health_intensity_minutes(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_intensity_minutes_range",
            return_value=[{"calendarDate": "2026-01-01", "moderateValue": 45, "vigorousValue": 15}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "health_intensity_minutes", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
        assert result["count"] == 1
        assert result["rows"][0]["moderate_value"] == 45

    def test_health_sleep(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_sleep", return_value=[{"dailySleepDTO": {"calendarDate": "2026-01-01", "sleepTimeSeconds": 28800}}])
        server = create_mcp_server(_config())
        result = _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["date"] == "2026-01-01"

    def test_health_hrv(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_hrv", return_value={"hrvSummaries": [{"calendarDate": "2026-01-01", "weeklyAvg": 45, "lastNightAvg": 42, "status": "BALANCED"}]})
        server = create_mcp_server(_config())
        result = _call(server, "health_hrv", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["weekly_avg"] == 45

    def test_health_weight(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_weight", return_value={"dateWeightList": [{"calendarDate": "2026-01-01", "weight": 75000, "bmi": 23.5, "bodyFat": 15.0}]})
        server = create_mcp_server(_config())
        result = _call(server, "health_weight", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["weight_kg"] == 75.0

    def test_health_body_battery(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_body_battery_range", return_value=[{"calendarDate": "2026-01-01", "bodyBatteryValuesArray": [[1735689600, 80], [1735775999, 30]]}])
        server = create_mcp_server(_config())
        result = _call(server, "health_body_battery", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1

    def test_health_stress(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_stress_range", return_value=[{"calendarDate": "2026-01-01", "avgStressLevel": 35, "maxStressLevel": 70}])
        server = create_mcp_server(_config())
        result = _call(server, "health_stress", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["avg_stress"] == 35

    def test_health_spo2(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_spo2_range", return_value=[{"dateTime": "2026-01-01", "averageSpO2": 97, "lowestSpO2": 94}])
        server = create_mcp_server(_config())
        result = _call(server, "health_spo2", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["avg_spo2"] == 97

    def test_health_resting_hr(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_resting_hr_range", return_value=[{"calendarDate": "2026-01-01", "restingHeartRateValue": 55}])
        server = create_mcp_server(_config())
        result = _call(server, "health_resting_hr", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["resting_hr"] == 55

    def test_health_readiness(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_training_readiness_range", return_value=[{"calendarDate": "2026-01-01", "score": 75, "level": "MODERATE"}])
        server = create_mcp_server(_config())
        result = _call(server, "health_readiness", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["score"] == 75

    def test_health_training_status(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_training_status", return_value={"calendarDate": "2026-01-01", "trainingStatusType": "PRODUCTIVE", "trainingLoadType": "OPTIMAL"})
        server = create_mcp_server(_config())
        result = _call(server, "health_training_status", {"date": "2026-01-01"})
        assert result["count"] == 1
        assert result["rows"][0]["training_status"] == "PRODUCTIVE"


# ---------------------------------------------------------------------------
# Happy path -- activity tools
# ---------------------------------------------------------------------------

class TestActivityTools:

    def test_activity_list(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.list_activities", return_value=[{"activityId": 1, "startTimeLocal": "2026-01-01", "activityName": "Run", "activityType": {"typeKey": "running"}, "distance": 5000, "duration": 1800, "averageHR": 150}])
        server = create_mcp_server(_config())
        result = _call(server, "activity_list", {"limit": 10})
        assert result["count"] == 1
        assert result["rows"][0]["id"] == 1

    def test_activity_list_with_filters(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mock_list = mocker.patch("garmin_cli.mcp_server.list_activities", return_value=[])
        server = create_mcp_server(_config())
        _call(server, "activity_list", {"limit": 5, "start": 10, "activity_type": "running", "search": "morning"})
        mock_list.assert_called_once_with(5, 10, "running", "morning", None, None)

    def test_activity_list_with_date_range(self, mocker: Any) -> None:
        from datetime import date

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mock_list = mocker.patch("garmin_cli.mcp_server.list_activities", return_value=[])
        server = create_mcp_server(_config())
        _call(server, "activity_list", {"start_date": "2026-03-01", "end_date": "2026-03-10"})
        mock_list.assert_called_once_with(20, 0, None, None, date(2026, 3, 1), date(2026, 3, 10))

    def test_activity_list_start_date_only_raises(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        server = create_mcp_server(_config())
        with pytest.raises(Exception, match="start_date and end_date must be provided together"):
            _call(server, "activity_list", {"start_date": "2026-03-15"})

    def test_activity_list_end_date_only_raises(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        server = create_mcp_server(_config())
        with pytest.raises(Exception, match="start_date and end_date must be provided together"):
            _call(server, "activity_list", {"end_date": "2026-03-10"})

    def test_activity_get(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_activity", return_value={"activityId": 123, "startTimeLocal": "2026-01-01", "activityName": "Run", "activityType": {"typeKey": "running"}, "distance": 10000, "duration": 3600, "averageHR": 155})
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 123})
        assert result["count"] == 1
        assert result["rows"][0]["id"] == 123

    def test_activity_get_detail_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={
                "activityId": 123,
                "startTimeLocal": "2026-01-01",
                "activityName": "Run",
                "activityType": {"typeKey": "running"},
                "distance": 10000,
                "duration": 3600,
                "averageHR": 155,
                "maxHR": 178,
                "calories": 650,
                "elevationGain": 120.0,
                "elevationLoss": 100.0,
                "averageSpeed": 2.778,
                "maxSpeed": 4.0,
                "averageRunningCadenceInStepsPerMinute": 180.0,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 123, "detail": True})
        assert result["count"] == 1
        row = result["rows"][0]
        assert "max_hr" in row
        assert "calories" in row
        assert "elevation_gain_m" in row
        assert "avg_speed_kmh" in row
        assert "avg_cadence_spm" in row

    def test_activity_get_default_compact(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={
                "activityId": 123,
                "startTimeLocal": "2026-01-01",
                "activityName": "Run",
                "activityType": {"typeKey": "running"},
                "distance": 10000,
                "duration": 3600,
                "averageHR": 155,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 123})
        assert result["count"] == 1
        row = result["rows"][0]
        assert "id" in row
        assert "max_hr" not in row

    def test_activity_get_detail_false_compact(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={
                "activityId": 123,
                "startTimeLocal": "2026-01-01",
                "activityName": "Run",
                "activityType": {"typeKey": "running"},
                "distance": 10000,
                "duration": 3600,
                "averageHR": 155,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 123, "detail": False})
        assert result["count"] == 1
        row = result["rows"][0]
        assert "id" in row
        assert "max_hr" not in row

    def test_activity_get_detail_returns_running_dynamics(self, mocker: Any) -> None:
        """U5: MCP activity_get(detail=True) on a run returns running-dynamics keys."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={
                "activityId": 200,
                "activityType": {"typeKey": "running"},
                "averageRunningCadenceInStepsPerMinute": 180.0,
                "avgGroundContactTime": 240,
                "avgVerticalOscillation": 8.4,
                "avgVerticalRatio": 6.5,
                "avgStrideLength": 132.0,
                "aerobicTrainingEffect": 3.2,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 200, "detail": True})
        row = result["rows"][0]
        assert row["avg_cadence_spm"] == 180.0
        assert row["avg_ground_contact_time"] == 240
        assert row["avg_vertical_oscillation"] == 8.4
        assert row["aerobic_training_effect"] == 3.2

    def test_activity_get_detail_returns_union_keys_with_nulls(self, mocker: Any) -> None:
        """U5: MCP activity_get(detail=True) emits the union schema."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={
                "activityId": 201,
                "activityType": {"typeKey": "running"},
                "averageRunningCadenceInStepsPerMinute": 175.0,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 201, "detail": True})
        row = result["rows"][0]
        # cycling/swim union keys present but null
        for key in ("avg_power_w", "norm_power_w", "tss", "swolf", "total_strokes"):
            assert key in row
            assert row[key] is None

    def test_activity_get_detail_cycling_returns_power_suite(self, mocker: Any) -> None:
        """U5: MCP activity_get(detail=True) on a ride returns cycling power keys."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={
                "activityId": 300,
                "activityType": {"typeKey": "cycling"},
                "averagePower": 220.0,
                "maxPower": 600.0,
                "normPower": 235.0,
                "trainingStressScore": 95.0,
                "intensityFactor": 0.88,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 300, "detail": True})
        row = result["rows"][0]
        assert row["avg_power_w"] == 220.0
        assert row["norm_power_w"] == 235.0
        assert row["tss"] == 95.0
        assert row["intensity_factor"] == 0.88

    def test_activity_get_detail_lap_swim_returns_swim_metrics(self, mocker: Any) -> None:
        """U5: MCP activity_get(detail=True) on a swim returns swim aggregates."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={
                "activityId": 400,
                "activityType": {"typeKey": "lap_swimming"},
                "avgSwolf": 38,
                "strokes": 720,
                "averageStrokeRate": 28.5,
                "avgStrokeDistance": 1.85,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 400, "detail": True})
        row = result["rows"][0]
        assert row["swolf"] == 38
        assert row["total_strokes"] == 720
        assert row["avg_stroke_rate"] == 28.5
        assert row["distance_per_stroke"] == 1.85

    def test_activity_weather(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity_weather",
            return_value={
                "temp": 20,
                "apparentTemp": 19,
                "dewPoint": 10,
                "relativeHumidity": 60,
                "windSpeed": 5,
                "windGust": 8,
                "windDirection": 180,
                "windDirectionCompassPoint": "s",
                "weatherTypeDTO": {"desc": "Cloudy"},
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_weather", {"activity_id": 123})
        assert result["count"] == 1
        row = result["rows"][0]
        assert row["temperature"] == 20
        assert row["humidity"] == 60
        assert row["wind_direction"] == 180
        assert row["condition"] == "Cloudy"

    def test_activity_get_detail_emits_unavailable_manifest(self, mocker: Any) -> None:
        """U11: detail=True attaches unavailable[] to MCP envelope when non-empty."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "running"}},
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 1, "detail": True})
        assert "unavailable" in result
        reasons = {e["field"]: e["reason"] for e in result["unavailable"]}
        assert reasons.get("avg_power_w") == "not_applicable_to_sport"
        assert reasons.get("swolf") == "not_applicable_to_sport"

    def test_activity_get_detail_false_omits_manifest(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "running"}},
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 1, "detail": False})
        assert "unavailable" not in result

    def test_activity_get_multisport_unions_child_manifests(self, mocker: Any) -> None:
        """U11: multisport parent envelope unions children with leg_index."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={
                "activityId": 100,
                "activityType": {"typeKey": "multi_sport"},
                "isMultiSportParent": True,
                "childIds": [101, 102, 103],
            },
        )
        mocker.patch(
            "garmin_cli.mcp_server.get_multisport_children",
            return_value=[
                {"activityId": 101, "activityType": {"typeKey": "open_water_swimming"}, "averageHR": 145},
                {"activityId": 102, "activityType": {"typeKey": "cycling"}, "averagePower": 200},
                {"activityId": 103, "activityType": {"typeKey": "running"}, "averageRunningCadenceInStepsPerMinute": 175},
            ],
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 100, "detail": True})
        assert "unavailable" in result
        leg_indices = {e["leg_index"] for e in result["unavailable"]}
        assert leg_indices == {0, 1, 2}

    def test_activity_get_summary_no_manifest_for_simple_activity(self, mocker: Any) -> None:
        """detail=False never carries manifest, even for unknown sports."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "weightlifting"}},
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 1})
        assert "unavailable" not in result

    def test_activity_laps_run_uses_raw_splits(self, mocker: Any) -> None:
        """U8: running activity routes to get_activity_splits (raw URL)."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={"activityId": 123, "activityType": {"typeKey": "running"}},
        )
        splits = mocker.patch(
            "garmin_cli.mcp_server.get_activity_splits",
            return_value={"lapDTOs": [
                {"duration": 480, "distance": 1000, "averageHR": 162, "avgGroundContactTime": 235},
                {"duration": 470, "distance": 1000, "averageHR": 168, "avgGroundContactTime": 230},
            ]},
        )
        typed = mocker.patch("garmin_cli.mcp_server.get_activity_typed_splits")
        server = create_mcp_server(_config())
        result = _call(server, "activity_laps", {"activity_id": 123})
        assert result["count"] == 2
        assert result["rows"][0]["avg_ground_contact_time"] == 235
        splits.assert_called_once_with(123)
        typed.assert_not_called()

    def test_activity_laps_pool_swim_uses_typed_splits(self, mocker: Any) -> None:
        """U8: lap_swimming routes to get_activity_typed_splits (typed method)."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={"activityId": 456, "activityType": {"typeKey": "lap_swimming"}},
        )
        splits = mocker.patch("garmin_cli.mcp_server.get_activity_splits")
        typed = mocker.patch(
            "garmin_cli.mcp_server.get_activity_typed_splits",
            return_value={"lengthDTOs": [
                {"duration": 25.0, "distance": 25.0, "swolf": 38, "swimStroke": "FREESTYLE", "strokes": 14},
                {"duration": 26.0, "distance": 25.0, "swolf": 39, "swimStroke": "FREESTYLE", "strokes": 15},
            ]},
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_laps", {"activity_id": 456})
        assert result["count"] == 2
        assert result["rows"][0]["swolf"] == 38
        assert result["rows"][0]["stroke_type"] == "FREESTYLE"
        typed.assert_called_once_with(456)
        splits.assert_not_called()

    def test_activity_laps_open_water_swim_uses_raw_splits(self, mocker: Any) -> None:
        """U8: open_water_swimming routes to splits (lapDTOs), not typed_splits."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={"activityId": 789, "activityType": {"typeKey": "open_water_swimming"}},
        )
        splits = mocker.patch(
            "garmin_cli.mcp_server.get_activity_splits",
            return_value={"lapDTOs": [{"duration": 600, "distance": 1000, "averageHR": 140}]},
        )
        typed = mocker.patch("garmin_cli.mcp_server.get_activity_typed_splits")
        server = create_mcp_server(_config())
        result = _call(server, "activity_laps", {"activity_id": 789})
        assert result["count"] == 1
        splits.assert_called_once()
        typed.assert_not_called()

    def test_activity_laps_invalid_id_raises_tool_error(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_laps", {"activity_id": 0})

    def test_activity_laps_multisport_fan_out_with_leg_index(self, mocker: Any) -> None:
        """Multisport parent laps fetches each child and stamps leg_index."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity",
            return_value={
                "activityId": 100,
                "activityType": {"typeKey": "multi_sport"},
                "isMultiSportParent": True,
                "childIds": [101, 102, 103],
            },
        )
        mocker.patch(
            "garmin_cli.mcp_server.get_multisport_children",
            return_value=[
                {"activityId": 101, "activityType": {"typeKey": "open_water_swimming"}},
                {"activityId": 102, "activityType": {"typeKey": "cycling"}},
                {"activityId": 103, "activityType": {"typeKey": "running"}},
            ],
        )
        mocker.patch(
            "garmin_cli.mcp_server.get_activity_splits",
            side_effect=[
                {"lapDTOs": [{"duration": 600, "distance": 1000, "averageHR": 140}]},
                {"lapDTOs": [{"duration": 1200, "distance": 8000, "averagePower": 220}]},
                {"lapDTOs": [{"duration": 900, "distance": 3000, "avgGroundContactTime": 235}]},
            ],
        )
        mocker.patch("garmin_cli.mcp_server.get_activity_typed_splits")
        server = create_mcp_server(_config())
        result = _call(server, "activity_laps", {"activity_id": 100})
        assert result["count"] == 3
        leg_indices = {row["leg_index"] for row in result["rows"]}
        assert leg_indices == {0, 1, 2}

    def test_activity_hr_zones_returns_envelope(self, mocker: Any) -> None:
        """U10: activity_hr_zones returns one row per zone."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity_hr_in_timezones",
            return_value=[
                {"zoneNumber": z, "zoneLowBoundary": 100 + z, "zoneHighBoundary": 110 + z, "secsInZone": 60 * z}
                for z in range(1, 6)
            ],
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_hr_zones", {"activity_id": 1})
        assert result["count"] == 5
        assert result["rows"][0]["zone"] == 1
        assert result["rows"][4]["zone"] == 5

    def test_activity_hr_zones_empty_returns_zero_count(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_activity_hr_in_timezones", return_value=[])
        server = create_mcp_server(_config())
        result = _call(server, "activity_hr_zones", {"activity_id": 1})
        assert result["count"] == 0
        assert result["rows"] == []

    def test_activity_hr_zones_invalid_id_raises_tool_error(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_hr_zones", {"activity_id": -1})

    def test_activity_metrics_describe_returns_descriptors(self, mocker: Any) -> None:
        """U12: activity_metrics_describe returns one row per metric descriptor."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_activity_details",
            return_value={"metricDescriptors": [
                {"key": "directHeartRate", "unit": {"key": "bpm"}, "metricsIndex": 0},
                {"key": "directPower", "unit": {"key": "W"}, "metricsIndex": 1},
            ]},
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_metrics_describe", {"activity_id": 1})
        assert result["count"] == 2
        keys = {row["key"] for row in result["rows"]}
        assert keys == {"directHeartRate", "directPower"}

    def test_activity_metrics_describe_empty(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_activity_details", return_value={})
        server = create_mcp_server(_config())
        result = _call(server, "activity_metrics_describe", {"activity_id": 1})
        assert result["count"] == 0
        assert result["rows"] == []

    def test_activity_metrics_describe_invalid_id(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_metrics_describe", {"activity_id": 0})


# ---------------------------------------------------------------------------
# Happy path -- workout tools
# ---------------------------------------------------------------------------

class TestWorkoutTools:

    def test_workout_list(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.list_workouts", return_value=[{"workoutId": 1, "workoutName": "Easy Run", "sportType": {"sportTypeKey": "running"}, "estimatedDurationInSecs": 1800}])
        server = create_mcp_server(_config())
        result = _call(server, "workout_list", {"limit": 10})
        assert result["count"] == 1
        assert result["rows"][0]["name"] == "Easy Run"

    def test_workout_get(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_workout", return_value={"workoutId": 1, "workoutName": "Easy Run", "sportType": {"sportTypeKey": "running"}, "estimatedDurationInSecs": 1800, "workoutSegments": []})
        server = create_mcp_server(_config())
        result = _call(server, "workout_get", {"workout_id": 1})
        assert result["count"] == 1

    def test_workout_calendar(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_calendar_range", return_value=[{"date": "2026-01-01", "workoutId": 1, "title": "Easy Run", "workoutTypeKey": "running", "durationInSeconds": 1800}])
        server = create_mcp_server(_config())
        result = _call(server, "workout_calendar", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# Workout write tools -- workout_create
# ---------------------------------------------------------------------------


_VALID_WORKOUT = {
    "name": "Easy Run",
    "sport": "running",
    "steps": [
        {
            "type": "interval",
            "duration": {"type": "time", "value": 1800},
            "target": {"type": "no.target"},
        }
    ],
}


class TestMcpWorkoutCreate:
    """workout_create: validate / build / dry_run / live / errors / logging."""

    def test_live_create_happy_path(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        create = mocker.patch(
            "garmin_cli.mcp_server.create_workout",
            return_value={"workoutId": 12345, "workoutName": "Easy Run"},
        )
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "workout_create", {"workout": dict(_VALID_WORKOUT)})

        assert result["count"] == 1
        row = result["rows"][0]
        assert row == {"ok": True, "action": "created", "workout_id": 12345}
        create.assert_called_once()
        log.assert_called_once()
        event = log.call_args.args[0]
        assert event.tool == "workout_create"
        assert event.outcome == "success"
        assert event.dry_run is False
        assert event.workout_id == 12345
        assert event.name_len == len("Easy Run")

    def test_dry_run_skips_garmin_and_auth(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        create = mocker.patch("garmin_cli.mcp_server.create_workout")
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_create",
            {"workout": dict(_VALID_WORKOUT), "dry_run": True},
        )

        assert result["count"] == 1
        row = result["rows"][0]
        assert row["ok"] is True
        assert row["dry_run"] is True
        assert row["validation_report"] == {"ok": True}
        assert "wire_payload" in row
        assert row["wire_payload"]["workoutName"] == "Easy Run"
        # The load-bearing safety contract: dry-run never touches Garmin or auth.
        auth.assert_not_called()
        create.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "dry-run"
        assert event.dry_run is True

    def test_validation_error_returns_envelope(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        create = mocker.patch("garmin_cli.mcp_server.create_workout")
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        bad = {"name": "x", "sport": "running", "steps": []}  # empty steps
        result = _call(server, "workout_create", {"workout": bad})

        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        assert isinstance(row["errors"], list)
        assert any("steps" in e for e in row["errors"])
        auth.assert_not_called()
        create.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "failed-validation"
        assert event.errors_count == len(row["errors"])

    def test_validation_warmupp_typo(self, mocker: Any) -> None:
        """AE5: a step with type='warmupp' is rejected by the validator."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.create_workout")
        mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        bad = {
            "name": "Easy Run",
            "sport": "running",
            "steps": [
                {
                    "type": "warmupp",
                    "duration": {"type": "time", "value": 600},
                    "target": {"type": "no.target"},
                }
            ],
        }
        result = _call(server, "workout_create", {"workout": bad})
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        assert any("warmupp" in e for e in row["errors"])

    def test_dry_run_with_validation_errors(self, mocker: Any) -> None:
        """dry_run=True does not bypass validation."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        create = mocker.patch("garmin_cli.mcp_server.create_workout")
        mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_create",
            {"workout": {"name": "x", "sport": "running", "steps": []}, "dry_run": True},
        )
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        create.assert_not_called()

    def test_auth_missing_on_live(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_server.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "workout_create", {"workout": dict(_VALID_WORKOUT)})

        event = log.call_args.args[0]
        assert event.outcome == "failed-auth"

    def test_dry_run_skips_auth_failure(self, mocker: Any) -> None:
        """dry_run=True does not call ensure_authenticated even when it would fail."""
        auth = mocker.patch(
            "garmin_cli.mcp_server.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_create",
            {"workout": dict(_VALID_WORKOUT), "dry_run": True},
        )
        assert result["rows"][0]["ok"] is True
        auth.assert_not_called()

    def test_upstream_failure(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.create_workout",
            side_effect=GarminCliError(error="Internal server error.", error_code="SERVER_ERROR"),
        )
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Internal server error"):
            _call(server, "workout_create", {"workout": dict(_VALID_WORKOUT)})

        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"


# ---------------------------------------------------------------------------
# Workout write tools -- workout_schedule
# ---------------------------------------------------------------------------


def _tool_annotations(server: Any, tool_name: str) -> Any:
    tools = asyncio.run(server.list_tools())
    for t in tools:
        if t.name == tool_name:
            return t.annotations
    raise AssertionError(f"tool {tool_name!r} not registered")


class TestMcpWorkoutSchedule:

    def test_happy_path(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.schedule_workout",
            return_value={"workoutScheduleId": 9988, "calendarDate": "2026-06-01"},
        )
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_schedule",
            {"workout_id": 12345, "date": "2026-06-01"},
        )

        row = result["rows"][0]
        assert row == {
            "ok": True,
            "action": "scheduled",
            "workout_id": 12345,
            "workout_schedule_id": 9988,
            "date": "2026-06-01",
        }
        event = log.call_args.args[0]
        assert event.tool == "workout_schedule"
        assert event.outcome == "success"
        assert event.workout_id == 12345

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "workout_schedule")
        assert ann is not None
        assert ann.destructive_hint is True

    def test_bad_date_format(self, mocker: Any) -> None:
        schedule = mocker.patch("garmin_cli.mcp_server.schedule_workout")
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="Invalid date format"):
            _call(server, "workout_schedule", {"workout_id": 1, "date": "not-a-date"})
        schedule.assert_not_called()

    def test_invalid_workout_id(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "workout_schedule", {"workout_id": 0, "date": "2026-01-01"})

    def test_auth_missing(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_server.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "workout_schedule", {"workout_id": 1, "date": "2026-06-01"})

        event = log.call_args.args[0]
        assert event.outcome == "failed-auth"

    def test_upstream_not_found(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.schedule_workout",
            side_effect=GarminCliError(error="Not found.", error_code="NOT_FOUND"),
        )
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Not found"):
            _call(server, "workout_schedule", {"workout_id": 99, "date": "2026-06-01"})

        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"


# ---------------------------------------------------------------------------
# Workout write tools -- workout_update (merge semantics)
# ---------------------------------------------------------------------------


_EXISTING_WORKOUT = {
    "workoutId": 42,
    "workoutName": "Old Name",
    "ownerId": 99,
    "createdDate": "2025-12-01T00:00:00",
    "atpPlanId": 7,
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSegments": [
        {
            "segmentOrder": 1,
            "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
            "workoutSteps": [],
        }
    ],
}


class TestMcpWorkoutUpdate:

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "workout_update")
        assert ann is not None
        assert ann.destructive_hint is True

    def test_dry_run_reads_but_does_not_write(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        get = mocker.patch(
            "garmin_cli.mcp_server.get_workout",
            return_value=dict(_EXISTING_WORKOUT),
        )
        update = mocker.patch("garmin_cli.mcp_server.update_workout")
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_update",
            {"workout_id": 42, "workout": {"name": "New Name"}, "dry_run": True},
        )

        row = result["rows"][0]
        assert row["ok"] is True
        assert row["dry_run"] is True
        assert "wire_payload" in row
        assert row["wire_payload"]["workoutName"] == "New Name"
        # Lineage preserved by merge_workout_payload deepcopy.
        assert row["wire_payload"]["workoutId"] == 42
        assert row["wire_payload"]["ownerId"] == 99
        assert row["wire_payload"]["atpPlanId"] == 7
        get.assert_called_once_with(42)
        update.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "dry-run"
        assert event.dry_run is True

    def test_live_update_calls_both_get_and_update(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_workout",
            return_value=dict(_EXISTING_WORKOUT),
        )
        update = mocker.patch("garmin_cli.mcp_server.update_workout")
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_update",
            {"workout_id": 42, "workout": {"name": "New Name"}},
        )

        row = result["rows"][0]
        assert row == {"ok": True, "action": "updated", "workout_id": 42}
        update.assert_called_once()
        called_workout_id, called_payload = update.call_args.args
        assert called_workout_id == 42
        assert called_payload["workoutName"] == "New Name"
        # The merged payload preserves the existing workoutId and atpPlanId.
        assert called_payload["workoutId"] == 42
        assert called_payload["atpPlanId"] == 7
        event = log.call_args.args[0]
        assert event.outcome == "success"

    def test_merge_warnings_in_dry_run(self, mocker: Any) -> None:
        """When user_input contains read-only fields, merge_workout_payload
        emits a warning that surfaces in the dry-run validation_report."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_workout",
            return_value=dict(_EXISTING_WORKOUT),
        )
        mocker.patch("garmin_cli.mcp_server.update_workout")
        mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_update",
            {
                "workout_id": 42,
                "workout": {"name": "New Name", "workoutId": 999},
                "dry_run": True,
            },
        )
        warnings = result["rows"][0]["validation_report"]["warnings"]
        assert any("workoutId" in w for w in warnings)

    def test_validation_error_blocks_garmin_calls(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        get = mocker.patch("garmin_cli.mcp_server.get_workout")
        update = mocker.patch("garmin_cli.mcp_server.update_workout")
        mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        # Empty string name -- fails partial validator.
        result = _call(
            server,
            "workout_update",
            {"workout_id": 42, "workout": {"name": ""}},
        )
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        auth.assert_not_called()
        get.assert_not_called()
        update.assert_not_called()

    def test_auth_missing(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_server.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        get = mocker.patch("garmin_cli.mcp_server.get_workout")
        update = mocker.patch("garmin_cli.mcp_server.update_workout")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "workout_update", {"workout_id": 42, "workout": {"name": "x"}})

        get.assert_not_called()
        update.assert_not_called()

    def test_get_workout_404(self, mocker: Any) -> None:
        """When the workout to update doesn't exist, fail before writing."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_workout",
            side_effect=GarminCliError(error="Not found.", error_code="NOT_FOUND"),
        )
        update = mocker.patch("garmin_cli.mcp_server.update_workout")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Not found"):
            _call(server, "workout_update", {"workout_id": 42, "workout": {"name": "x"}})

        update.assert_not_called()

    def test_update_workout_upstream_failure(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_workout",
            return_value=dict(_EXISTING_WORKOUT),
        )
        mocker.patch(
            "garmin_cli.mcp_server.update_workout",
            side_effect=GarminCliError(error="Internal server error.", error_code="SERVER_ERROR"),
        )
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Internal server error"):
            _call(server, "workout_update", {"workout_id": 42, "workout": {"name": "x"}})

        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"

    def test_update_workout_auth_failed_during_write(self, mocker: Any) -> None:
        """AUTH_FAILED during update_workout should log as 'failed-auth', not 'failed-upstream'."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_workout",
            return_value=dict(_EXISTING_WORKOUT),
        )
        mocker.patch(
            "garmin_cli.mcp_server.update_workout",
            side_effect=GarminCliError(error="Token expired.", error_code="AUTH_FAILED"),
        )
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError):
            _call(server, "workout_update", {"workout_id": 42, "workout": {"name": "x"}})

        event = log.call_args.args[0]
        assert event.outcome == "failed-auth"

    def test_invalid_workout_id(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "workout_update", {"workout_id": 0, "workout": {"name": "x"}})


# ---------------------------------------------------------------------------
# Workout write tools -- workout_delete
# ---------------------------------------------------------------------------


class TestMcpWorkoutDelete:

    def test_happy_path(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        delete = mocker.patch("garmin_cli.mcp_server.delete_workout")
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "workout_delete", {"workout_id": 12345})
        row = result["rows"][0]
        assert row == {"ok": True, "action": "deleted", "workout_id": 12345}
        delete.assert_called_once_with(12345)
        event = log.call_args.args[0]
        assert event.tool == "workout_delete"
        assert event.outcome == "success"
        assert event.workout_id == 12345

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "workout_delete")
        assert ann is not None
        assert ann.destructive_hint is True

    def test_invalid_workout_id(self, mocker: Any) -> None:
        delete = mocker.patch("garmin_cli.mcp_server.delete_workout")
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "workout_delete", {"workout_id": -1})
        delete.assert_not_called()

    def test_auth_missing(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_server.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        delete = mocker.patch("garmin_cli.mcp_server.delete_workout")
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "workout_delete", {"workout_id": 1})

        delete.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "failed-auth"

    @pytest.mark.parametrize("error_code", ["NOT_FOUND", "AUTH_FAILED"])
    def test_upstream_not_found_or_auth_failed(
        self, mocker: Any, error_code: str
    ) -> None:
        """AE4: Garmin returns NOT_FOUND or AUTH_FAILED for inaccessible IDs."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.delete_workout",
            side_effect=GarminCliError(error="Inaccessible.", error_code=error_code),
        )
        log = mocker.patch("garmin_cli.mcp_server._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError):
            _call(server, "workout_delete", {"workout_id": 999999999})

        event = log.call_args.args[0]
        expected_outcome = "failed-auth" if error_code == "AUTH_FAILED" else "failed-upstream"
        assert event.outcome == expected_outcome


# ---------------------------------------------------------------------------
# Happy path -- performance tools
# ---------------------------------------------------------------------------

class TestPerformanceTools:

    def test_performance_race_predictions(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        # Live flat-dict shape, so the MCP tool path exercises the reshape gate.
        mocker.patch(
            "garmin_cli.mcp_server.get_race_predictions",
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

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_endurance_score_range",
            return_value=[{"calendarDate": "2026-01-01", "overallScore": 5100}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "performance_endurance_score", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
        assert result["count"] == 1
        assert result["rows"][0]["overall_score"] == 5100

    def test_performance_hill_score(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_hill_score_range",
            return_value=[{"calendarDate": "2026-01-01", "overallScore": 42}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "performance_hill_score", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
        assert result["count"] == 1
        assert result["rows"][0]["overall_score"] == 42

    def test_performance_thresholds(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_all_thresholds", return_value={"thresholds": [{"sport": "running", "lactateThresholdHeartRate": 168}]})
        server = create_mcp_server(_config())
        result = _call(server, "performance_thresholds", {})
        assert result["count"] == 1

    def test_performance_vo2max_with_date(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_vo2max", return_value=[{"calendarDate": "2026-01-01", "generic": {"vo2MaxValue": 48, "calendarDate": "2026-01-01"}}])
        server = create_mcp_server(_config())
        result = _call(server, "performance_vo2max", {"date": "2026-01-01"})
        assert result["count"] >= 1

    def test_performance_vo2max_latest(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_latest_vo2max", return_value=[
            {"generic": {"vo2MaxValue": 48, "calendarDate": "2026-01-01"}},
            {"generic": {"vo2MaxValue": 49, "calendarDate": "2026-01-05"}},
        ])
        server = create_mcp_server(_config())
        result = _call(server, "performance_vo2max", {})
        # Should filter to latest date only
        assert all(row["date"] == "2026-01-05" for row in result["rows"])

    def test_performance_zones(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_lactate_threshold", return_value=[{"sport": "running", "lactateThresholdHeartRate": 168}])
        server = create_mcp_server(_config())
        result = _call(server, "performance_zones", {})
        assert result["count"] >= 1


# ---------------------------------------------------------------------------
# Happy path -- device tools
# ---------------------------------------------------------------------------

class TestDeviceTools:

    def test_device_list(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_devices",
            return_value=[{"deviceId": 1, "displayName": "Forerunner", "deviceTypeName": "WATCH"}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "device_list", {})
        assert result["count"] == 1
        assert result["rows"][0]["display_name"] == "Forerunner"


# ---------------------------------------------------------------------------
# Login status
# ---------------------------------------------------------------------------

class TestLoginStatus:

    def test_login_status_authenticated(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server._secure_directory")
        mocker.patch("garmin_cli.mcp_server.garth")
        mocker.patch("garmin_cli.mcp_server._probe_session")
        server = create_mcp_server(_config())
        result = _call(server, "login_status", {})
        assert result["authenticated"] is True
        assert "garmin_home" in result

    def test_login_status_not_authenticated(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server._secure_directory")
        mocker.patch("garmin_cli.mcp_server.garth")
        mocker.patch("garmin_cli.mcp_server.garth.resume", side_effect=FileNotFoundError)
        server = create_mcp_server(_config())
        result = _call(server, "login_status", {})
        assert result["authenticated"] is False

    def test_login_status_symlink_raises(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server._secure_directory", side_effect=GarminCliError(error="symlink", error_code="AUTH_FAILED"))
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="symlink"):
            _call(server, "login_status", {})


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------

class TestErrorPropagation:

    def test_garmin_cli_error_becomes_tool_error(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_sleep", side_effect=GarminCliError(error="Rate limited by Garmin API.", error_code="RATE_LIMITED"))
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="Rate limited"):
            _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})

    def test_auth_missing_includes_login_hint(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated", side_effect=GarminCliError(error="No usable saved session found", error_code="AUTH_MISSING"))
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})

    def test_auth_failed_no_login_hint(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated", side_effect=GarminCliError(error="garth_home path is a symlink", error_code="AUTH_FAILED"))
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="symlink") as exc_info:
            _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert "garmin-cli login" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------

class TestEnvelopeShape:
    """All tools must return {"count": N, "rows": [...]}."""

    def test_envelope_has_count_and_rows(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_sleep", return_value=[])
        server = create_mcp_server(_config())
        result = _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert "count" in result
        assert "rows" in result
        assert isinstance(result["rows"], list)
        assert result["count"] == len(result["rows"])

    def test_empty_result_envelope(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.list_activities", return_value=[])
        server = create_mcp_server(_config())
        result = _call(server, "activity_list", {"limit": 10})
        assert result == {"count": 0, "rows": []}


# ---------------------------------------------------------------------------
# Config passthrough
# ---------------------------------------------------------------------------

class TestConfigPassthrough:

    def test_garth_home_reaches_auth(self, mocker: Any) -> None:

        mock_auth = mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_sleep", return_value=[])
        config = _config(garth_home="/custom/garth")
        server = create_mcp_server(config)
        _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        passed_config = mock_auth.call_args[0][0]
        assert passed_config.garth_home == "/custom/garth"


# ---------------------------------------------------------------------------
# Import guard (CLI command)
# ---------------------------------------------------------------------------

class TestImportGuard:

    def test_mcp_import_error_shows_message(self, mocker: Any) -> None:
        from click.testing import CliRunner
        from garmin_cli.cli import cli

        mocker.patch.dict("sys.modules", {"garmin_cli.mcp_server": None})
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["mcp-server"])
        assert result.exit_code == 1
        assert 'pip install "garmin-cli[mcp]"' in (result.output + (result.stderr or ""))


# ---------------------------------------------------------------------------
# report_snapshot composite tool
# ---------------------------------------------------------------------------

class TestCollectReportSections:
    """Unit-test the per-section fan-out / isolation helper directly."""

    def test_ok_sections_collected(self) -> None:
        from garmin_cli.mcp_server import _collect_report_sections

        specs = [
            ("a", lambda: [1], lambda raw: [{"v": 1}]),
            ("b", lambda: [2], lambda raw: [{"v": 2}]),
        ]
        sections, unavailable = _collect_report_sections(specs)
        assert sections == {"a": [{"v": 1}], "b": [{"v": 2}]}
        assert unavailable == []

    def test_empty_section_marked_no_data(self) -> None:
        from garmin_cli.mcp_server import _collect_report_sections

        specs = [("a", lambda: [], lambda raw: [])]
        sections, unavailable = _collect_report_sections(specs)
        assert sections == {"a": []}
        assert unavailable == [{"section": "a", "reason": "no_data"}]

    def test_not_found_isolated(self) -> None:
        from garmin_cli.mcp_server import _collect_report_sections

        def boom() -> Any:
            raise GarminCliError(error="missing", error_code="NOT_FOUND")

        specs = [
            ("a", boom, lambda raw: [{"v": 1}]),
            ("b", lambda: [2], lambda raw: [{"v": 2}]),
        ]
        sections, unavailable = _collect_report_sections(specs)
        assert sections == {"a": [], "b": [{"v": 2}]}
        assert unavailable == [{"section": "a", "reason": "not_found"}]

    def test_fatal_error_propagates(self) -> None:
        from garmin_cli.mcp_server import _collect_report_sections

        def rate_limited() -> Any:
            raise GarminCliError(error="slow down", error_code="RATE_LIMITED")

        specs = [("a", rate_limited, lambda raw: [{"v": 1}])]
        with pytest.raises(GarminCliError) as exc:
            _collect_report_sections(specs)
        assert exc.value.error_code == "RATE_LIMITED"


class TestReportSnapshot:

    def _server(self) -> Any:
        return create_mcp_server(_config())

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(ToolError, match="kind must be one of"):
            _call(self._server(), "report_snapshot", {"kind": "yearly"})

    def test_morning_sections_and_single_day_range(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_sleep",
            return_value=[{"dailySleepDTO": {"calendarDate": "2026-06-12", "sleepTimeSeconds": 28800}}],
        )
        mocker.patch("garmin_cli.mcp_server.get_hrv", return_value={"hrvSummaries": []})
        mocker.patch("garmin_cli.mcp_server.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_body_battery_range", return_value=[])
        cal = mocker.patch("garmin_cli.mcp_server.get_calendar_range", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

        assert result["kind"] == "morning"
        assert result["date_range"] == {"from": "2026-06-12", "to": "2026-06-12"}
        assert set(result["sections"]) == {"sleep", "hrv", "readiness", "body_battery", "planned_today"}
        assert len(result["sections"]["sleep"]) == 1
        # planned_today fetches the anchor day
        cal.assert_called_once_with(date(2026, 6, 12), date(2026, 6, 12))

    def test_evening_planned_tomorrow_uses_next_day(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        for fn in ("get_steps_range", "get_intensity_minutes_range", "get_stress_range", "get_body_battery_range"):
            mocker.patch(f"garmin_cli.mcp_server.{fn}", return_value=[])
        mocker.patch("garmin_cli.mcp_server.list_activities", return_value=[])
        cal = mocker.patch("garmin_cli.mcp_server.get_calendar_range", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "evening", "date": "2026-06-12"})

        assert result["kind"] == "evening"
        assert set(result["sections"]) == {
            "steps", "intensity_minutes", "stress", "body_battery", "activities_today", "planned_tomorrow",
        }
        cal.assert_called_once_with(date(2026, 6, 13), date(2026, 6, 13))

    def test_weekly_spans_seven_days(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        for fn in (
            "get_sleep", "get_hrv", "get_stress_range", "get_steps_range",
            "get_resting_hr_range", "get_body_battery_range", "get_endurance_score_range",
        ):
            mocker.patch(f"garmin_cli.mcp_server.{fn}", return_value=[])
        mocker.patch("garmin_cli.mcp_server.list_activities", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_race_predictions", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "weekly", "date": "2026-06-12"})

        assert result["kind"] == "weekly"
        assert result["date_range"] == {"from": "2026-06-06", "to": "2026-06-12"}
        assert "endurance_score" in result["sections"]
        assert "race_predictions" in result["sections"]

    def test_not_found_section_degrades_gracefully(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_sleep",
            side_effect=GarminCliError(error="no sleep", error_code="NOT_FOUND"),
        )
        mocker.patch(
            "garmin_cli.mcp_server.get_hrv",
            return_value={"hrvSummaries": [{"calendarDate": "2026-06-12", "lastNightAvg": 42}]},
        )
        mocker.patch("garmin_cli.mcp_server.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_body_battery_range", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_calendar_range", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

        assert result["sections"]["sleep"] == []
        assert {"section": "sleep", "reason": "not_found"} in result["unavailable"]
        assert len(result["sections"]["hrv"]) == 1  # other sections still populated

    def test_fatal_error_fails_whole_snapshot(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_sleep",
            side_effect=GarminCliError(error="rate limited", error_code="RATE_LIMITED"),
        )
        # Sections fetch concurrently, so the other sections run even though
        # the first one fails — they must be patched to keep the test offline.
        mocker.patch("garmin_cli.mcp_server.get_hrv", return_value={"hrvSummaries": []})
        mocker.patch("garmin_cli.mcp_server.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_body_battery_range", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_calendar_range", return_value=[])
        with pytest.raises(ToolError, match="rate limited"):
            _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

    def test_fatal_error_in_later_section_fails_whole_snapshot(self, mocker: Any) -> None:
        """A non-recoverable error must fail the snapshot even when it comes
        from the last section and every earlier section succeeded."""
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_sleep", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_hrv", return_value={"hrvSummaries": []})
        mocker.patch("garmin_cli.mcp_server.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_body_battery_range", return_value=[])
        mocker.patch(
            "garmin_cli.mcp_server.get_calendar_range",
            side_effect=GarminCliError(error="upstream broke", error_code="SERVER_ERROR"),
        )
        with pytest.raises(ToolError, match="upstream broke"):
            _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

    def test_sections_keep_spec_order_despite_completion_order(
        self, mocker: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Section ordering is the spec order, not completion order: the first
        section is forced to finish last and must still be listed first."""
        monkeypatch.setenv("GARMIN_CLI_FETCH_CONCURRENCY", "4")
        gate = threading.Event()

        def slow_sleep(*args: Any) -> list:
            assert gate.wait(timeout=10), "gating section never ran"
            return [{"dailySleepDTO": {"calendarDate": "2026-06-12", "sleepTimeSeconds": 28800}}]

        def gate_opener(*args: Any) -> list:
            gate.set()
            return []

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_sleep", side_effect=slow_sleep)
        mocker.patch("garmin_cli.mcp_server.get_hrv", return_value={"hrvSummaries": []})
        mocker.patch("garmin_cli.mcp_server.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_body_battery_range", side_effect=gate_opener)
        mocker.patch("garmin_cli.mcp_server.get_calendar_range", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

        assert list(result["sections"]) == [
            "sleep", "hrv", "readiness", "body_battery", "planned_today",
        ]
        assert len(result["sections"]["sleep"]) == 1

    def test_auth_missing_fails_with_hint(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_server.ensure_authenticated",
            side_effect=GarminCliError(error="not logged in", error_code="AUTH_MISSING"),
        )
        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

    def test_defaults_to_today_when_date_omitted(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")

        class _FixedDate(date):
            @classmethod
            def today(cls) -> date:
                return date(2026, 6, 12)

        mocker.patch("garmin_cli.mcp_server.date_cls", _FixedDate)
        mocker.patch("garmin_cli.mcp_server.get_sleep", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_hrv", return_value={"hrvSummaries": []})
        mocker.patch("garmin_cli.mcp_server.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_body_battery_range", return_value=[])
        mocker.patch("garmin_cli.mcp_server.get_calendar_range", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "morning"})
        assert result["date_range"] == {"from": "2026-06-12", "to": "2026-06-12"}
