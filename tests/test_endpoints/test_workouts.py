"""Tests for garmin_cli.endpoints.workouts — list_workouts, get_workout, get_calendar_range."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.workouts import (
    get_calendar_range,
    get_workout,
    list_workouts,
)
from garmin_cli.exceptions import GarminCliError
from garmin_cli.serializers import serialize_calendar_workout
from tests.helpers import make_http_error as _http_error


# ---------------------------------------------------------------------------
# list_workouts
# ---------------------------------------------------------------------------

class TestListWorkouts:

    def test_returns_list(self, mocker: Any, sample_workouts_list_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.list_workouts.return_value = sample_workouts_list_raw
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = list_workouts(limit=20)
        assert isinstance(result, list)

    def test_empty_result(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.list_workouts.return_value = []
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = list_workouts(limit=20)
        assert result == []

    def test_http_500_raises_server_error_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.list_workouts.side_effect = [_http_error(500)] * 4
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            list_workouts(limit=20)
        assert exc_info.value.error_code == "SERVER_ERROR"


# ---------------------------------------------------------------------------
# get_workout
# ---------------------------------------------------------------------------

class TestGetWorkout:

    def test_returns_workout_data(self, mocker: Any, sample_workout_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_workout.return_value = sample_workout_raw
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = get_workout(987654)
        assert result is not None

    def test_http_404_raises_not_found_error_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_workout.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_workout(99999)
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_string_workout_id(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_workout.return_value = {}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        get_workout("987654")
        mock_garth.get_workout.assert_called_once_with(987654)


# ---------------------------------------------------------------------------
# get_calendar_range
# ---------------------------------------------------------------------------

class TestGetCalendarRange:

    def test_returns_list(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {"calendarItems": []}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = get_calendar_range(date(2026, 3, 11), date(2026, 3, 17))
        assert isinstance(result, list)

    def test_iterates_weekly_for_multi_week_range(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {"calendarItems": []}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        # 3-week range should trigger multiple API calls (one per week)
        get_calendar_range(date(2026, 3, 1), date(2026, 3, 21))
        assert mock_garth.connectapi.call_count >= 2

    def test_collects_workout_items_from_all_weeks(
        self, mocker: Any, sample_calendar_raw: Any
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_calendar_raw
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        result = get_calendar_range(date(2026, 3, 1), date(2026, 3, 14))
        assert isinstance(result, list)

    def test_filters_items_outside_requested_date_range(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {
            "calendarItems": [
                {"date": "2026-03-10", "title": "Before"},
                {"date": "2026-03-11", "title": "Inside"},
                {"date": "2026-03-15", "title": "After"},
            ]
        }
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = get_calendar_range(date(2026, 3, 11), date(2026, 3, 12))
        assert result == [{"date": "2026-03-11", "title": "Inside"}]

    def test_empty_calendar_returns_empty_list(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {"calendarItems": []}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = get_calendar_range(date(2026, 3, 11), date(2026, 3, 17))
        assert result == []

    def test_single_day_range(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {"calendarItems": []}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = get_calendar_range(date(2026, 3, 11), date(2026, 3, 11))
        assert result is not None

    def test_http_429_raises_rate_limited_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [_http_error(429)] * 4
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            get_calendar_range(date(2026, 3, 11), date(2026, 3, 17))
        assert exc_info.value.error_code == "RATE_LIMITED"

    def test_uses_verified_weekly_calendar_endpoint(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {"calendarItems": []}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        get_calendar_range(date(2026, 3, 11), date(2026, 3, 17))
        call_str = str(mock_garth.connectapi.call_args_list[0])
        assert "/calendar-service/year/2026/month/2/day/11/start/1" in call_str


def _by_period_entry(schedule_id: int, day: str, workout_id: int = 77) -> dict[str, Any]:
    # Shape verified against the live workoutScheduleByPeriod endpoint (2026-11-09).
    return {
        "workoutScheduleId": schedule_id,
        "calendarDate": day,
        "workout": {
            "workoutId": workout_id,
            "workoutName": "Coach Base",
            "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
            "trainingPlanId": None,
            "atpPlanId": 5,
        },
    }


class TestCalendarIncludesScheduledByPeriod:
    """Adaptive (Garmin Coach) sessions only appear in workoutScheduleByPeriod."""

    def _patch(self, mocker: Any, calendar_items: list[Any], by_period: Any) -> MagicMock:
        mock_garth = MagicMock()

        def connectapi(path: str, **kwargs: Any) -> Any:
            if path.startswith("/workout-service/schedule/workoutScheduleByPeriod"):
                if isinstance(by_period, Exception):
                    raise by_period
                return by_period
            return {"calendarItems": calendar_items}

        mock_garth.connectapi.side_effect = connectapi
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")
        return mock_garth

    def test_adds_schedule_missing_from_calendar_as_calendar_item(self, mocker: Any) -> None:
        mock_garth = self._patch(mocker, [], [_by_period_entry(9001, "2026-03-12")])

        result = get_calendar_range(date(2026, 3, 11), date(2026, 3, 17))

        assert result == [{
            "id": 9001,
            "itemType": "workout",
            "date": "2026-03-12",
            "workoutId": 77,
            "title": "Coach Base",
            "sportTypeKey": "running",
            "trainingPlanId": None,
            "atpPlanId": 5,
        }]
        mock_garth.connectapi.assert_any_call(
            "/workout-service/schedule/workoutScheduleByPeriod",
            params={"startDate": "2026-03-11", "endDate": "2026-03-17"},
        )
        row = serialize_calendar_workout({"calendarItems": result})[0]
        assert (row["workout_schedule_id"], row["workout_id"], row["name"]) == (9001, 77, "Coach Base")

    def test_skips_schedules_already_on_the_calendar(self, mocker: Any) -> None:
        on_calendar = {"id": 9001, "itemType": "workout", "date": "2026-03-12", "workoutId": 77, "title": "Base"}
        self._patch(mocker, [on_calendar], [_by_period_entry(9001, "2026-03-12")])

        assert get_calendar_range(date(2026, 3, 11), date(2026, 3, 17)) == [on_calendar]

    def test_merged_items_are_date_ordered_and_range_filtered(self, mocker: Any) -> None:
        on_calendar = {"id": 1, "itemType": "workout", "date": "2026-03-14", "workoutId": 2, "title": "Later"}
        by_period = [_by_period_entry(9001, "2026-03-12"), _by_period_entry(9002, "2026-03-30")]
        self._patch(mocker, [on_calendar], by_period)

        result = get_calendar_range(date(2026, 3, 11), date(2026, 3, 17))

        assert [item["id"] for item in result] == [9001, 1]

    @pytest.mark.parametrize("status", [404, 403, 500])
    def test_by_period_failure_keeps_calendar_items(self, mocker: Any, status: int) -> None:
        on_calendar = {"id": 1, "itemType": "workout", "date": "2026-03-14", "workoutId": 2, "title": "Run"}
        self._patch(mocker, [on_calendar], _http_error(status))

        assert get_calendar_range(date(2026, 3, 11), date(2026, 3, 17)) == [on_calendar]

    def test_by_period_server_error_fails_fast(self, mocker: Any) -> None:
        self._patch(mocker, [], _http_error(503))
        sleep = mocker.patch("time.sleep")

        assert get_calendar_range(date(2026, 3, 11), date(2026, 3, 17)) == []
        sleep.assert_not_called()

    def test_by_period_transport_failure_keeps_calendar_items(self, mocker: Any) -> None:
        on_calendar = {"id": 1, "itemType": "workout", "date": "2026-03-14", "workoutId": 2, "title": "Run"}
        self._patch(mocker, [on_calendar], TimeoutError("read timed out"))

        assert get_calendar_range(date(2026, 3, 11), date(2026, 3, 17)) == [on_calendar]

    def test_live_calendar_sport_key_fills_type(self) -> None:
        live_item = {"id": 5, "itemType": "workout", "date": "2026-03-14", "workoutId": 2, "sportTypeKey": "running"}
        assert serialize_calendar_workout({"calendarItems": [live_item]})[0]["type"] == "running"

    def test_by_period_rate_limit_still_fails_the_calendar(self, mocker: Any) -> None:
        self._patch(mocker, [], _http_error(429))

        with pytest.raises(GarminCliError) as exc_info:
            get_calendar_range(date(2026, 3, 11), date(2026, 3, 17))
        assert exc_info.value.error_code == "RATE_LIMITED"
