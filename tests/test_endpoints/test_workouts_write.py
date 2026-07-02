"""Tests for write operations in garmin_cli.endpoints.workouts."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.workouts import (
    create_workout,
    delete_workout,
    schedule_workout,
    unschedule_workout,
    update_workout,
)
from garmin_cli.exceptions import GarminCliError
from tests.helpers import make_http_error as _http_error


# ---------------------------------------------------------------------------
# Shared sample payloads
# ---------------------------------------------------------------------------

_SAMPLE_PAYLOAD: dict = {
    "workoutName": "Morning Run",
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSegments": [],
}

_SAMPLE_EXISTING: dict = {
    "workoutId": 12345,
    "ownerId": 9999,
    "workoutName": "Old Name",
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSegments": [],
}


# ---------------------------------------------------------------------------
# create_workout
# ---------------------------------------------------------------------------

class TestCreateWorkout:

    def test_returns_created_workout_dict(self, mocker: Any) -> None:
        expected = {**_SAMPLE_PAYLOAD, "workoutId": 42}
        mock_garth = MagicMock()
        mock_garth.create_workout.return_value = expected
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = create_workout(_SAMPLE_PAYLOAD)
        assert isinstance(result, dict)
        assert result.get("workoutId") == 42

    def test_400_raises_invalid_input(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.create_workout.side_effect = _http_error(400)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            create_workout(_SAMPLE_PAYLOAD)
        assert exc_info.value.error_code == "INVALID_INPUT"

    def test_401_raises_auth_failed(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.create_workout.side_effect = _http_error(401)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            create_workout(_SAMPLE_PAYLOAD)
        assert exc_info.value.error_code == "AUTH_FAILED"

    def test_500_retries_and_raises(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.create_workout.side_effect = [_http_error(500)] * 4
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            create_workout(_SAMPLE_PAYLOAD)
        assert exc_info.value.error_code == "SERVER_ERROR"


# ---------------------------------------------------------------------------
# update_workout
# ---------------------------------------------------------------------------

class TestUpdateWorkout:

    def test_returns_none_for_204(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = None
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = update_workout(12345, _SAMPLE_EXISTING)
        assert result is None

    def test_invalid_workout_id_raises_invalid_input(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            update_workout("not-a-number", _SAMPLE_EXISTING)
        assert exc_info.value.error_code == "INVALID_INPUT"

    def test_404_raises_not_found(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            update_workout(99999, _SAMPLE_EXISTING)
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_403_raises_auth_failed(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(403)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            update_workout(12345, _SAMPLE_EXISTING)
        assert exc_info.value.error_code == "AUTH_FAILED"


# ---------------------------------------------------------------------------
# delete_workout
# ---------------------------------------------------------------------------

class TestDeleteWorkout:

    def test_calls_typed_delete_with_workout_id(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.delete_workout.return_value = None
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        delete_workout(12345)
        mock_garth.delete_workout.assert_called_once_with(12345)

    def test_returns_none_on_success(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.delete_workout.return_value = None
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = delete_workout(12345)
        assert result is None

    def test_invalid_workout_id_raises_invalid_input(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            delete_workout("not-a-number")
        assert exc_info.value.error_code == "INVALID_INPUT"

    def test_404_raises_not_found(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.delete_workout.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            delete_workout(99999)
        assert exc_info.value.error_code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# schedule_workout
# ---------------------------------------------------------------------------

class TestScheduleWorkout:

    def test_passes_date_as_iso_string(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.schedule_workout.return_value = {
            "workoutScheduleId": 555,
            "calendarDate": "2026-04-01",
        }
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        schedule_workout(12345, date(2026, 4, 1))
        mock_garth.schedule_workout.assert_called_once_with(12345, date(2026, 4, 1))

    def test_returns_schedule_dict(self, mocker: Any) -> None:
        expected = {"workoutScheduleId": 555, "calendarDate": "2026-04-01"}
        mock_garth = MagicMock()
        mock_garth.schedule_workout.return_value = expected
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = schedule_workout(12345, date(2026, 4, 1))
        assert isinstance(result, dict)
        assert result.get("workoutScheduleId") == 555

    def test_invalid_workout_id_raises_invalid_input(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            schedule_workout("not-a-number", date(2026, 4, 1))
        assert exc_info.value.error_code == "INVALID_INPUT"

    def test_404_raises_not_found(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.schedule_workout.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            schedule_workout(99999, date(2026, 4, 1))
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_invalid_date_does_not_crash(self, mocker: Any) -> None:
        """Passing a date object (not a string) should work without crashing."""
        mock_garth = MagicMock()
        mock_garth.schedule_workout.return_value = {
            "workoutScheduleId": 777,
            "calendarDate": "2026-04-01",
        }
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = schedule_workout(12345, date(2026, 4, 1))
        assert result is not None


# ---------------------------------------------------------------------------
# unschedule_workout
# ---------------------------------------------------------------------------

class TestUnscheduleWorkout:

    def test_calls_typed_unschedule_with_validated_id(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.unschedule_workout.return_value = None
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        unschedule_workout(555)
        mock_garth.unschedule_workout.assert_called_once_with(555)

    def test_returns_none_on_success(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.unschedule_workout.return_value = None
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        assert unschedule_workout(555) is None

    def test_invalid_schedule_id_raises_invalid_input(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            unschedule_workout("not-a-number")
        assert exc_info.value.error_code == "INVALID_INPUT"
        mock_garth.unschedule_workout.assert_not_called()

    def test_404_raises_not_found(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.unschedule_workout.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            unschedule_workout(99999)
        assert exc_info.value.error_code == "NOT_FOUND"
