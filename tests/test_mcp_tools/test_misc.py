"""Device / login / report_snapshot / serializer MCP tool tests (moved from test_mcp_server.py; assertions unchanged)."""
from __future__ import annotations

import threading
from datetime import date
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli import serializers as garmin_serializers  # noqa: E402
from garmin_cli.endpoints import devices as devices_endpoints  # noqa: E402
from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


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


class TestDeviceTools:

    def test_device_list(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.misc.get_devices",
            return_value=[{"deviceId": 1, "displayName": "Forerunner", "deviceTypeName": "WATCH"}],
        )
        server = create_mcp_server(_config())
        result = _call(server, "device_list", {})
        assert result["count"] == 1
        assert result["rows"][0]["display_name"] == "Forerunner"


class TestLoginStatus:

    def test_login_status_authenticated(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools.misc._secure_directory")
        mocker.patch("garmin_cli.mcp_tools.misc.garth")
        mocker.patch("garmin_cli.mcp_tools.misc._probe_session")
        server = create_mcp_server(_config())
        result = _call(server, "login_status", {})
        assert result["authenticated"] is True
        assert "garmin_home" in result

    def test_login_status_not_authenticated(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools.misc._secure_directory")
        mocker.patch("garmin_cli.mcp_tools.misc.garth")
        mocker.patch("garmin_cli.mcp_tools.misc.garth.resume", side_effect=FileNotFoundError)
        server = create_mcp_server(_config())
        result = _call(server, "login_status", {})
        assert result["authenticated"] is False

    def test_login_status_symlink_raises(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools.misc._secure_directory", side_effect=GarminCliError(error="symlink", error_code="AUTH_FAILED"))
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="symlink"):
            _call(server, "login_status", {})


class TestSubmitMfaCode:

    def test_submit_mfa_code_success(self, mocker: Any) -> None:
        mock_complete = mocker.patch("garmin_cli.mcp_tools.misc.complete_mfa_login")
        server = create_mcp_server(_config())
        result = _call(server, "submit_mfa_code", {"mfa_code": " 123456 "})
        assert result["authenticated"] is True
        assert "garmin_home" in result
        assert mock_complete.call_args[0][1] == "123456"  # whitespace stripped

    def test_submit_mfa_code_empty_raises(self, mocker: Any) -> None:
        mock_complete = mocker.patch("garmin_cli.mcp_tools.misc.complete_mfa_login")
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="non-empty"):
            _call(server, "submit_mfa_code", {"mfa_code": "   "})
        mock_complete.assert_not_called()

    def test_submit_mfa_code_no_pending_login(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_tools.misc.complete_mfa_login",
            side_effect=GarminCliError(
                error="No Garmin login is awaiting an MFA code.",
                error_code="INVALID_INPUT",
            ),
        )
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="awaiting an MFA code"):
            _call(server, "submit_mfa_code", {"mfa_code": "123456"})

    def test_submit_mfa_code_rejected_code(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_tools.misc.complete_mfa_login",
            side_effect=GarminCliError(
                error="MFA verification failed.",
                error_code="AUTH_FAILED",
            ),
        )
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="MFA verification failed"):
            _call(server, "submit_mfa_code", {"mfa_code": "000000"})


class TestReportSnapshot:

    def _server(self) -> Any:
        return create_mcp_server(_config())

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(ToolError, match="kind must be one of"):
            _call(self._server(), "report_snapshot", {"kind": "yearly"})

    def test_morning_sections_and_single_day_range(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.misc.get_sleep",
            return_value=[{"dailySleepDTO": {"calendarDate": "2026-06-12", "sleepTimeSeconds": 28800}}],
        )
        mocker.patch("garmin_cli.mcp_tools.misc.get_hrv", return_value={"hrvSummaries": []})
        mocker.patch("garmin_cli.mcp_tools.misc.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_body_battery_range", return_value=[])
        cal = mocker.patch("garmin_cli.mcp_tools.misc.get_calendar_range", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

        assert result["kind"] == "morning"
        assert result["date_range"] == {"from": "2026-06-12", "to": "2026-06-12"}
        assert set(result["sections"]) == {"sleep", "hrv", "readiness", "body_battery", "planned_today"}
        assert len(result["sections"]["sleep"]) == 1
        # planned_today fetches the anchor day
        cal.assert_called_once_with(date(2026, 6, 12), date(2026, 6, 12))

    def test_evening_planned_tomorrow_uses_next_day(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        for fn in ("get_steps_range", "get_intensity_minutes_range", "get_stress_range", "get_body_battery_range"):
            mocker.patch(f"garmin_cli.mcp_tools.misc.{fn}", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.list_activities", return_value=[])
        cal = mocker.patch("garmin_cli.mcp_tools.misc.get_calendar_range", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "evening", "date": "2026-06-12"})

        assert result["kind"] == "evening"
        assert set(result["sections"]) == {
            "steps", "intensity_minutes", "stress", "body_battery", "activities_today", "planned_tomorrow",
        }
        cal.assert_called_once_with(date(2026, 6, 13), date(2026, 6, 13))

    def test_weekly_spans_seven_days(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        for fn in (
            "get_sleep", "get_hrv", "get_stress_range", "get_steps_range",
            "get_resting_hr_range", "get_body_battery_range", "get_endurance_score_range",
        ):
            mocker.patch(f"garmin_cli.mcp_tools.misc.{fn}", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.list_activities", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_race_predictions", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "weekly", "date": "2026-06-12"})

        assert result["kind"] == "weekly"
        assert result["date_range"] == {"from": "2026-06-06", "to": "2026-06-12"}
        assert "endurance_score" in result["sections"]
        assert "race_predictions" in result["sections"]

    def test_not_found_section_degrades_gracefully(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.misc.get_sleep",
            side_effect=GarminCliError(error="no sleep", error_code="NOT_FOUND"),
        )
        mocker.patch(
            "garmin_cli.mcp_tools.misc.get_hrv",
            return_value={"hrvSummaries": [{"calendarDate": "2026-06-12", "lastNightAvg": 42}]},
        )
        mocker.patch("garmin_cli.mcp_tools.misc.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_body_battery_range", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_calendar_range", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

        assert result["sections"]["sleep"] == []
        assert {"section": "sleep", "reason": "not_found"} in result["unavailable"]
        assert len(result["sections"]["hrv"]) == 1  # other sections still populated

    def test_fatal_error_fails_whole_snapshot(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.misc.get_sleep",
            side_effect=GarminCliError(error="rate limited", error_code="RATE_LIMITED"),
        )
        # Sections fetch concurrently, so the other sections run even though
        # the first one fails — they must be patched to keep the test offline.
        mocker.patch("garmin_cli.mcp_tools.misc.get_hrv", return_value={"hrvSummaries": []})
        mocker.patch("garmin_cli.mcp_tools.misc.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_body_battery_range", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_calendar_range", return_value=[])
        with pytest.raises(ToolError, match="rate limited"):
            _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

    def test_fatal_error_in_later_section_fails_whole_snapshot(self, mocker: Any) -> None:
        """A non-recoverable error must fail the snapshot even when it comes
        from the last section and every earlier section succeeded."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.misc.get_sleep", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_hrv", return_value={"hrvSummaries": []})
        mocker.patch("garmin_cli.mcp_tools.misc.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_body_battery_range", return_value=[])
        mocker.patch(
            "garmin_cli.mcp_tools.misc.get_calendar_range",
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

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.misc.get_sleep", side_effect=slow_sleep)
        mocker.patch("garmin_cli.mcp_tools.misc.get_hrv", return_value={"hrvSummaries": []})
        mocker.patch("garmin_cli.mcp_tools.misc.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_body_battery_range", side_effect=gate_opener)
        mocker.patch("garmin_cli.mcp_tools.misc.get_calendar_range", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

        assert list(result["sections"]) == [
            "sleep", "hrv", "readiness", "body_battery", "planned_today",
        ]
        assert len(result["sections"]["sleep"]) == 1

    def test_auth_missing_fails_with_hint(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_tools._shared.ensure_authenticated",
            side_effect=GarminCliError(error="not logged in", error_code="AUTH_MISSING"),
        )
        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(self._server(), "report_snapshot", {"kind": "morning", "date": "2026-06-12"})

    def test_defaults_to_today_when_date_omitted(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")

        class _FixedDate(date):
            @classmethod
            def today(cls) -> date:
                return date(2026, 6, 12)

        mocker.patch("garmin_cli.mcp_tools.misc.date_cls", _FixedDate)
        mocker.patch("garmin_cli.mcp_tools.misc.get_sleep", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_hrv", return_value={"hrvSummaries": []})
        mocker.patch("garmin_cli.mcp_tools.misc.get_training_readiness_range", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_body_battery_range", return_value=[])
        mocker.patch("garmin_cli.mcp_tools.misc.get_calendar_range", return_value=[])

        result = _call(self._server(), "report_snapshot", {"kind": "morning"})
        assert result["date_range"] == {"from": "2026-06-12", "to": "2026-06-12"}
