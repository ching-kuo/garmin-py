"""Tests for garmin_cli.endpoints.workouts — list_workouts, get_workout, get_calendar_range."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.workouts import (
    get_calendar_range,
    get_calendar_range_counted,
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


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize(
    ("method", "call"),
    [("list_workouts", lambda: list_workouts(limit=20)), ("get_workout", lambda: get_workout(1))],
)
def test_workout_reads_map_auth_rejections_to_auth_failed(
    mocker: Any, status: int, method: str, call: Any
) -> None:
    mock_garth = MagicMock()
    getattr(mock_garth, method).side_effect = _http_error(status)
    mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

    with pytest.raises(GarminCliError) as exc_info:
        call()
    assert exc_info.value.error_code == "AUTH_FAILED"
    assert getattr(mock_garth, method).call_count == 1


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


class TestCalendarWeekWalk:
    """Live: each page is the Monday-Sunday week containing the requested day."""

    def _patch(
        self,
        mocker: Any,
        items: list[dict[str, Any]],
        by_period: Any = None,
        *,
        first_weekday: int = 0,
        end_date: str | None = None,
        bounds: bool = True,
    ) -> MagicMock:
        """Pages are the week (starting on *first_weekday*, Monday=0) containing the day."""
        mock_garth = MagicMock()

        def connectapi(path: str, **kwargs: Any) -> Any:
            if path.startswith("/workout-service/schedule/workoutScheduleByPeriod"):
                return [] if by_period is None else by_period
            parts = path.split("/")
            day = date(int(parts[3]), int(parts[5]) + 1, int(parts[7]))
            week_start = day - timedelta(days=(day.weekday() - first_weekday) % 7)
            week_end = week_start + timedelta(days=6)
            page: dict[str, Any] = {
                "calendarItems": [
                    item for item in items if week_start.isoformat() <= item["date"] <= week_end.isoformat()
                ],
            }
            if bounds:
                page.update(startDate=week_start.isoformat(), endDate=end_date or week_end.isoformat())
            return page

        mock_garth.connectapi.side_effect = connectapi
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        return mock_garth

    def test_wednesday_to_next_tuesday_fetches_the_week_containing_end(self, mocker: Any) -> None:
        items = [
            {"id": 1, "itemType": "activity", "date": "2026-11-17", "workoutId": None},
            {"id": 2, "itemType": "workout", "date": "2026-11-19", "workoutId": 7},
            {"id": 3, "itemType": "weight", "date": "2026-11-23", "workoutId": None},
            {"id": 4, "itemType": "nap", "date": "2026-11-24", "workoutId": None},
            {"id": 5, "itemType": "activity", "date": "2026-11-25", "workoutId": None},
        ]
        self._patch(mocker, items)

        result = get_calendar_range(date(2026, 11, 18), date(2026, 11, 24))

        assert [item["id"] for item in result] == [2, 3, 4]

    def test_pages_are_deduplicated_across_overlapping_requests(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        page = {"calendarItems": [{"id": 2, "itemType": "workout", "date": "2026-11-19", "workoutId": 7}]}
        mock_garth.connectapi.side_effect = lambda path, **kwargs: [] if "ByPeriod" in path else page
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        # No startDate/endDate in the pages: the walk aligns to Monday and refetches.
        result = get_calendar_range(date(2026, 11, 18), date(2026, 11, 24))

        assert [item["id"] for item in result] == [2]

    def test_non_workout_item_id_does_not_hide_a_schedule(self, mocker: Any) -> None:
        items = [{"id": 9001, "itemType": "activity", "date": "2026-11-19", "workoutId": None}]
        self._patch(mocker, items, [_by_period_entry(9001, "2026-11-19")])

        result = get_calendar_range(date(2026, 11, 18), date(2026, 11, 24))

        assert [(item["itemType"], item["id"]) for item in result] == [("activity", 9001), ("workout", 9001)]
        rows = serialize_calendar_workout({"calendarItems": result})
        assert [row["workout_schedule_id"] for row in rows] == [None, 9001]

    def test_sunday_start_pages_cover_the_range(self, mocker: Any) -> None:
        items = [
            {"id": 1, "itemType": "activity", "date": "2026-11-22", "workoutId": None},
            {"id": 2, "itemType": "workout", "date": "2026-11-24", "workoutId": 7},
        ]
        mock_garth = self._patch(mocker, items, first_weekday=6)

        result = get_calendar_range(date(2026, 11, 18), date(2026, 11, 24))

        assert [item["id"] for item in result] == [1, 2]
        assert mock_garth.connectapi.call_count == 3  # two pages plus the by-period lookup

    def test_stale_end_date_falls_back_to_week_alignment(self, mocker: Any) -> None:
        items = [{"id": 3, "itemType": "weight", "date": "2026-11-24", "workoutId": None}]
        mock_garth = self._patch(mocker, items, end_date="2020-01-01")

        result = get_calendar_range(date(2026, 11, 18), date(2026, 12, 8))

        assert [item["id"] for item in result] == [3]
        # 21 days: at most ceil(21 / 7) + 1 page reads, plus the by-period lookup.
        assert mock_garth.connectapi.call_count <= 4 + 1

    def test_null_calendar_items_and_date_max_are_safe(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = lambda path, **kwargs: [] if "ByPeriod" in path else {"calendarItems": None}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        assert get_calendar_range(date.max - timedelta(days=2), date.max) == []

    def test_schedule_dedupe_matches_the_serializer(self, mocker: Any) -> None:
        # No itemType, schedule id only under workoutScheduleId: still a schedule.
        legacy = {"workoutScheduleId": 9003, "date": "2026-11-21", "workoutId": 77}
        on_calendar = {"id": 9004, "itemType": "workout", "date": "2026-11-22", "workoutId": 77}
        # An unknown type naming a workout (Garmin Coach) is a schedule.
        coach = {"id": 9005, "itemType": "fbtAdaptiveWorkout", "date": "2026-11-23", "workoutId": 78}
        # A known non-schedule item naming a workout is not, whatever its id.
        activity = {"id": 9001, "itemType": "activity", "date": "2026-11-19", "workoutId": 77}
        idless = {"itemType": "workout", "date": "2026-11-24", "workoutId": 79}
        by_period = [
            _by_period_entry(9001, "2026-11-19"),
            _by_period_entry(9002, "2026-11-20"),
            _by_period_entry(9002, "2026-11-20"),
            _by_period_entry(9003, "2026-11-21"),
            _by_period_entry(9004, "2026-11-22"),
            _by_period_entry(9005, "2026-11-23", workout_id=78),
        ]
        self._patch(mocker, [legacy, on_calendar, coach, activity, idless], by_period)

        result = get_calendar_range(date(2026, 11, 18), date(2026, 11, 24))
        rows = serialize_calendar_workout({"calendarItems": result})

        assert [(row["date"], row["workout_schedule_id"]) for row in rows] == [
            ("2026-11-19", None),
            ("2026-11-19", 9001),
            ("2026-11-20", 9002),
            ("2026-11-21", 9003),
            ("2026-11-22", 9004),
            ("2026-11-23", 9005),
            ("2026-11-24", None),
        ]

    def test_missing_bounds_still_query_the_end_date_page(self, mocker: Any) -> None:
        # Sunday-start account, pages without startDate/endDate, Wed..Sun.
        items = [{"id": 6, "itemType": "nap", "date": "2026-11-22", "workoutId": None}]
        mock_garth = self._patch(mocker, items, first_weekday=6, bounds=False)

        result = get_calendar_range(date(2026, 11, 18), date(2026, 11, 22))

        assert [item["id"] for item in result] == [6]
        assert mock_garth.connectapi.call_count <= 2 + 1

    @pytest.mark.parametrize(
        ("page", "by_period"),
        [
            ({"calendarItems": None}, []),
            ({"startDate": "2026-11-16"}, []),
            ("oops", []),
            ({"calendarItems": []}, {"message": "oops"}),
            ({"calendarItems": []}, "oops"),
        ],
    )
    def test_strict_read_rejects_unusable_responses(self, mocker: Any, page: Any, by_period: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = lambda path, **kwargs: by_period if "ByPeriod" in path else page
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError):
            get_calendar_range(date(2026, 11, 18), date(2026, 11, 18), strict=True)
        # Non-strict reads still treat them as empty.
        assert get_calendar_range(date(2026, 11, 18), date(2026, 11, 18)) == []

    @pytest.mark.parametrize(
        ("page", "by_period"),
        [({}, []), (None, []), ({"calendarItems": []}, {}), ({"calendarItems": []}, None)],
    )
    def test_strict_read_takes_no_content_as_an_empty_period(self, mocker: Any, page: Any, by_period: Any) -> None:
        # garminconnect turns an HTTP 204 into {} (or the request helper into None).
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = lambda path, **kwargs: by_period if "ByPeriod" in path else page
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        assert get_calendar_range(date(2026, 11, 18), date(2026, 11, 18), strict=True) == []

    def test_request_count_reports_pages_plus_lookup(self, mocker: Any) -> None:
        self._patch(mocker, [])

        items, requests = get_calendar_range_counted(date(2026, 11, 18), date(2026, 11, 24))

        assert (items, requests) == ([], 3)


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

    @pytest.mark.parametrize("failure", [_http_error(500), TimeoutError("read timed out")])
    def test_strict_read_fails_when_by_period_lookup_fails(self, mocker: Any, failure: Exception) -> None:
        # A recheck must not take a calendar-only read as proof a schedule is gone.
        on_calendar = {"id": 1, "itemType": "workout", "date": "2026-03-14", "workoutId": 2, "title": "Run"}
        self._patch(mocker, [on_calendar], failure)

        with pytest.raises(GarminCliError):
            get_calendar_range(date(2026, 3, 11), date(2026, 3, 17), strict=True)
        assert get_calendar_range(date(2026, 3, 11), date(2026, 3, 17)) == [on_calendar]

    def test_by_period_rate_limit_still_fails_the_calendar(self, mocker: Any) -> None:
        self._patch(mocker, [], _http_error(429))

        with pytest.raises(GarminCliError) as exc_info:
            get_calendar_range(date(2026, 3, 11), date(2026, 3, 17))
        assert exc_info.value.error_code == "RATE_LIMITED"
