"""Tests for the MCP server module (TDD -- written before implementation)."""
from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

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
        "workout_list",
        "workout_get",
        "workout_calendar",
        "performance_thresholds",
        "performance_race_predictions",
        "performance_endurance_score",
        "performance_hill_score",
        "performance_vo2max",
        "performance_zones",
        "device_list",
        "login_status",
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
        mock_request = mocker.patch(
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


# ---------------------------------------------------------------------------
# Endpoint layer -- metrics
# ---------------------------------------------------------------------------

class TestMetricsEndpoints:
    """Verify metrics endpoint helpers call Garmin APIs correctly."""


    def test_get_race_predictions(self, mocker: Any) -> None:
        mock_request = mocker.patch(
            "garmin_cli.endpoints.metrics._request",
            return_value=[{"raceType": "5K", "predictedTimeInSeconds": 1500}],
        )
        result = metrics_endpoints.get_race_predictions()
        assert result[0]["raceType"] == "5K"
        mock_request.assert_called_once_with("/metrics-service/metrics/racepredictions")

    def test_get_race_predictions_coalesces_none(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.endpoints.metrics._request", return_value=None)
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
        mocker.patch(
            "garmin_cli.endpoints.metrics._request",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        with pytest.raises(GarminCliError, match="Not found"):
            metrics_endpoints.get_race_predictions()


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

    def test_new_columns_contain_expected_fields(self) -> None:
        assert garmin_serializers.COLUMNS_DAILY_SUMMARY == (
            "date",
            "total_steps",
            "distance_km",
            "active_kilocalories",
            "floors_ascended",
            "floors_descended",
            "moderate_intensity_minutes",
            "vigorous_intensity_minutes",
            "resting_heart_rate",
        )
        assert garmin_serializers.COLUMNS_STEPS == (
            "date",
            "total_steps",
            "total_distance",
            "step_goal",
        )
        assert garmin_serializers.COLUMNS_INTENSITY_MINUTES == (
            "date",
            "moderate_value",
            "vigorous_value",
            "weekly_goal",
        )
        assert garmin_serializers.COLUMNS_RACE_PREDICTIONS == (
            "race_type",
            "predicted_time_seconds",
            "distance_meters",
        )
        assert garmin_serializers.COLUMNS_ENDURANCE_SCORE == (
            "date",
            "overall_score",
            "endurance_classification",
        )
        assert garmin_serializers.COLUMNS_HILL_SCORE == (
            "date",
            "overall_score",
            "endurance_score",
            "strength_score",
        )
        assert garmin_serializers.COLUMNS_DEVICE == (
            "device_id",
            "display_name",
            "device_type",
            "last_sync_time",
        )


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
        mock_list.assert_called_once_with(5, 10, "running", "morning")

    def test_activity_get(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_activity", return_value={"activityId": 123, "startTimeLocal": "2026-01-01", "activityName": "Run", "activityType": {"typeKey": "running"}, "distance": 10000, "duration": 3600, "averageHR": 155})
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 123})
        assert result["count"] == 1
        assert result["rows"][0]["id"] == 123

    def test_activity_weather(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_server.get_activity_weather", return_value={"temperature": 20, "weatherIconCode": "sunny", "windSpeed": 5, "windDirectionDegrees": 180, "humidity": 60, "precipProbability": 10})
        server = create_mcp_server(_config())
        result = _call(server, "activity_weather", {"activity_id": 123})
        assert result["count"] == 1
        assert result["rows"][0]["temperature"] == 20


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
# Happy path -- performance tools
# ---------------------------------------------------------------------------

class TestPerformanceTools:

    def test_performance_race_predictions(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_server.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_server.get_race_predictions",
            return_value=[{"raceType": "MARATHON", "predictedTimeInSeconds": 12600}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "performance_race_predictions", {})
        assert result["count"] == 1
        assert result["rows"][0]["race_type"] == "MARATHON"

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
        assert "garth_home" in result

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
