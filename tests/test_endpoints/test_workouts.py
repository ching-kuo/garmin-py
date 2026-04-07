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
from tests.helpers import make_http_error as _http_error


# ---------------------------------------------------------------------------
# list_workouts
# ---------------------------------------------------------------------------

class TestListWorkouts:

    def test_returns_list(self, mocker: Any, sample_workouts_list_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_workouts_list_raw
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = list_workouts(limit=20)
        assert isinstance(result, list)

    def test_empty_result(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = []
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = list_workouts(limit=20)
        assert result == []

    def test_http_500_raises_server_error_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [_http_error(500)] * 4
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
        mock_garth.connectapi.return_value = sample_workout_raw
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = get_workout(987654)
        assert result is not None

    def test_http_404_raises_not_found_error_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_workout(99999)
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_string_workout_id(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        get_workout("987654")
        call_str = str(mock_garth.connectapi.call_args)
        assert "987654" in call_str


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
        call_str = str(mock_garth.connectapi.call_args)
        assert "/calendar-service/year/2026/month/2/day/11/start/1" in call_str
