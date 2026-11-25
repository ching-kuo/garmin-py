"""Contract tests for the bounded coach snapshot MCP tool."""

from __future__ import annotations

from datetime import date as Date
from typing import Any

import pytest
import requests

from tests.helpers import require_mcp

require_mcp()

from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config, _tool_annotations  # noqa: E402


class TestCoachSnapshot:
    def test_read_only_annotation(self) -> None:
        annotations = _tool_annotations(create_mcp_server(_config()), "coach_snapshot")
        assert annotations is not None
        assert annotations.read_only_hint is True

    def test_terminal_rate_limit_preserves_prior_sections_and_stops(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        sleep = mocker.patch("garmin_cli.services.coaching_snapshot.get_sleep", return_value={})
        hrv = mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_hrv",
            side_effect=GarminCliError("slow down", "RATE_LIMITED"),
        )
        body_battery = mocker.patch("garmin_cli.services.coaching_snapshot.get_body_battery_range")
        server = create_mcp_server(_config())

        result = _call(server, "coach_snapshot", {"date": "2026-07-15"})

        assert result["complete"] is False
        assert result["aborted"] is True
        assert result["errors"] == [
            {
                "section": "hrv",
                "error_code": "RATE_LIMITED",
                "category": "rate_limit",
                "message": "Garmin data for this section was unavailable.",
                "recovery_hint": "Retry the snapshot later; do not retry immediately.",
            }
        ]
        assert result["provenance"]["completed_requests"] == 1
        auth.assert_called_once()
        sleep.assert_called_once()
        hrv.assert_called_once()
        body_battery.assert_not_called()

    def test_completed_requests_counts_calendar_pages_actually_read(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        for name in (
            "get_sleep", "get_hrv", "get_body_battery_range", "get_steps_range", "get_weight",
            "list_activities", "get_resting_hr_range", "get_stress_range",
            "get_stress", "get_training_readiness_range", "get_spo2", "get_training_status",
        ):
            mocker.patch(f"garmin_cli.services.coaching_snapshot.{name}", return_value=[])
        # The seven-date window fit in one calendar week: one page plus the lookup.
        mocker.patch("garmin_cli.services.coaching_snapshot.get_calendar_range_counted", return_value=([], 2))

        result = _call(create_mcp_server(_config()), "coach_snapshot", {"date": "2026-07-13"})

        # 6 ranged reads + resting-HR range and current-day fill (charged as
        # 2) + 9+1 stress days + readiness, SpO2, status + 2 calendar requests.
        assert result["provenance"]["estimated_requests"] == 24
        assert result["provenance"]["completed_requests"] == 23

    def test_resting_hr_is_one_range_request_split_into_current(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        for name in (
            "get_sleep", "get_hrv", "get_body_battery_range", "get_steps_range", "get_weight",
            "list_activities", "get_stress_range", "get_stress", "get_spo2", "get_training_status",
        ):
            mocker.patch(f"garmin_cli.services.coaching_snapshot.{name}", return_value=[])
        mocker.patch("garmin_cli.services.coaching_snapshot.get_calendar_range_counted", return_value=([], 2))
        days = [Date(2026, 7, 6 + offset) for offset in range(10)]
        rhr = mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_resting_hr_range",
            return_value=[{"calendarDate": day.isoformat(), "restingHeartRate": 50} for day in days[:-1]]
            + [{"calendarDate": "2026-07-15", "restingHeartRate": 44}],
        )
        readiness = mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_training_readiness_range", return_value=[]
        )

        result = _call(create_mcp_server(_config()), "coach_snapshot", {"date": "2026-07-15"})

        rhr.assert_called_once_with(Date(2026, 7, 6), Date(2026, 7, 15))
        readiness.assert_called_once_with(Date(2026, 7, 15), Date(2026, 7, 15))
        signal = next(s for s in result["recovery"]["signals"] if s["signal"] == "resting_heart_rate")
        assert signal["current_value"] == 44
        assert signal["current_value_date"] == "2026-07-15"
        assert signal["sample_count"] == 9
        assert signal["baseline_median"] == 50

    @pytest.mark.parametrize("code", ["NOT_FOUND", "SERVER_ERROR"])
    def test_failed_resting_hr_range_also_reports_the_current_value(self, mocker: Any, code: str) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        for name in (
            "get_sleep", "get_hrv", "get_body_battery_range", "get_steps_range", "get_weight",
            "list_activities", "get_stress_range", "get_stress", "get_training_readiness_range",
            "get_spo2", "get_training_status",
        ):
            mocker.patch(f"garmin_cli.services.coaching_snapshot.{name}", return_value=[{"calendarDate": "2026-07-15"}])
        mocker.patch("garmin_cli.services.coaching_snapshot.get_calendar_range_counted", return_value=([], 2))
        mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_resting_hr_range",
            side_effect=GarminCliError("gone", code),
        )

        result = _call(create_mcp_server(_config()), "coach_snapshot", {"date": "2026-07-15"})

        failures = result["unavailable"] if code == "NOT_FOUND" else result["errors"]
        assert {"resting_hr", "current_resting_hr"} <= {entry["section"] for entry in failures}

    def test_resting_hr_without_a_current_row_reports_current_no_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        for name in (
            "get_sleep", "get_hrv", "get_body_battery_range", "get_steps_range", "get_weight",
            "list_activities", "get_stress_range", "get_stress", "get_training_readiness_range",
            "get_spo2", "get_training_status",
        ):
            mocker.patch(f"garmin_cli.services.coaching_snapshot.{name}", return_value=[{"calendarDate": "2026-07-15"}])
        mocker.patch("garmin_cli.services.coaching_snapshot.get_calendar_range_counted", return_value=([], 2))
        mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_resting_hr_range",
            return_value=[{"calendarDate": "2026-07-14", "restingHeartRate": 50}],
        )

        result = _call(create_mcp_server(_config()), "coach_snapshot", {"date": "2026-07-15"})

        assert {"section": "current_resting_hr", "reason": "no_data"} in result["unavailable"]
        assert not any(entry["section"] == "resting_hr" for entry in result["unavailable"])

    def test_missing_current_resting_hr_is_not_backfilled_from_prior_days(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        for name in (
            "get_sleep", "get_hrv", "get_body_battery_range", "get_steps_range", "get_weight",
            "list_activities", "get_stress_range", "get_stress", "get_training_readiness_range",
            "get_spo2", "get_training_status",
        ):
            mocker.patch(f"garmin_cli.services.coaching_snapshot.{name}", return_value=[])
        mocker.patch("garmin_cli.services.coaching_snapshot.get_calendar_range_counted", return_value=([], 2))
        mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_resting_hr_range",
            return_value=[
                {"calendarDate": "2026-07-14", "restingHeartRate": 50},
                {"calendarDate": "2026-07-15", "restingHeartRate": None},
            ],
        )

        result = _call(create_mcp_server(_config()), "coach_snapshot", {"date": "2026-07-15"})

        signal = next(s for s in result["recovery"]["signals"] if s["signal"] == "resting_heart_rate")
        assert signal["state"] == "missing_current"

    def test_timed_out_section_is_recorded_and_snapshot_completes(
        self, mocker: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        for name in (
            "get_sleep", "get_body_battery_range", "get_steps_range", "get_weight",
            "list_activities", "get_resting_hr_range", "get_stress_range",
            "get_stress", "get_training_readiness_range", "get_spo2", "get_training_status",
        ):
            mocker.patch(f"garmin_cli.services.coaching_snapshot.{name}", return_value=[])
        mocker.patch("garmin_cli.services.coaching_snapshot.get_calendar_range_counted", return_value=([], 3))
        # The real get_hrv runs; its transport times out on every attempt.
        mocker.patch(
            "garmin_cli.endpoints.health.garth.connectapi",
            side_effect=requests.Timeout("read timed out"),
        )
        mocker.patch("time.sleep")
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "1")

        result = _call(create_mcp_server(_config()), "coach_snapshot", {"date": "2026-07-15"})

        assert result["complete"] is False
        assert result["aborted"] is False
        assert result["errors"] == [
            {
                "section": "hrv",
                "error_code": "NETWORK_ERROR",
                "category": "network",
                "message": "Garmin data for this section was unavailable.",
            }
        ]

    def test_extended_baseline_above_budget_fails_before_auth(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        server = create_mcp_server(_config())

        with pytest.raises(Exception, match="request budget"):
            _call(
                server,
                "coach_snapshot",
                {"date": "2026-07-15", "include_extended_daily_baselines": True},
            )
        auth.assert_not_called()

    def test_steps_window_is_capped_at_28_dates(self, mocker: Any) -> None:
        """Garmin's daily-steps endpoint 400s on spans wider than 28 dates."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        steps = mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_steps_range", return_value=[]
        )
        mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_weight",
            side_effect=GarminCliError("stop early", "RATE_LIMITED"),
        )
        for name in ("get_sleep", "get_hrv", "get_body_battery_range"):
            mocker.patch(
                f"garmin_cli.services.coaching_snapshot.{name}", return_value=[]
            )
        server = create_mcp_server(_config())

        _call(server, "coach_snapshot", {"date": "2026-07-15"})

        steps.assert_called_once_with(Date(2026, 6, 18), Date(2026, 7, 15))


def test_coach_snapshot_default_date_is_resolved_after_auth(mocker: Any) -> None:
    """The profile timezone is only known once a session exists."""
    order: list[str] = []
    mocker.patch(
        "garmin_cli.mcp_tools._shared.ensure_authenticated",
        side_effect=lambda config: order.append("auth"),
    )
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.today",
        side_effect=lambda: order.append("today") or Date(2030, 1, 2),
    )
    collect = mocker.patch("garmin_cli.mcp_tools.coaching.collect_snapshot", return_value={})

    _call(create_mcp_server(_config()), "coach_snapshot", {})

    assert order == ["auth", "today"]
    assert collect.call_args.args[0] == Date(2030, 1, 2)
