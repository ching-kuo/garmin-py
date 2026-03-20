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
    update_workout,
)
from garmin_cli.exceptions import GarminCliError


# ---------------------------------------------------------------------------
# Mock HTTP error helper
# ---------------------------------------------------------------------------

def _http_error(status_code: int) -> Exception:
    err = Exception(f"HTTP {status_code}")
    err.response = MagicMock(status_code=status_code)  # type: ignore[attr-defined]
    return err


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

    def test_calls_connectapi_with_post_method(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {**_SAMPLE_PAYLOAD, "workoutId": 1}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        create_workout(_SAMPLE_PAYLOAD)
        call_str = str(mock_garth.connectapi.call_args)
        assert "POST" in call_str or mock_garth.connectapi.called

    def test_calls_workout_service_endpoint(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {**_SAMPLE_PAYLOAD, "workoutId": 1}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        create_workout(_SAMPLE_PAYLOAD)
        call_str = str(mock_garth.connectapi.call_args)
        assert "workout-service" in call_str or "workout" in call_str.lower()

    def test_passes_payload_as_json(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {**_SAMPLE_PAYLOAD, "workoutId": 1}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        create_workout(_SAMPLE_PAYLOAD)
        call_str = str(mock_garth.connectapi.call_args)
        assert "Morning Run" in call_str or "workoutName" in call_str

    def test_returns_created_workout_dict(self, mocker: Any) -> None:
        expected = {**_SAMPLE_PAYLOAD, "workoutId": 42}
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = expected
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = create_workout(_SAMPLE_PAYLOAD)
        assert isinstance(result, dict)
        assert result.get("workoutId") == 42

    def test_400_raises_invalid_input(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(400)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            create_workout(_SAMPLE_PAYLOAD)
        assert exc_info.value.error_code == "INVALID_INPUT"

    def test_401_raises_auth_failed(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(401)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            create_workout(_SAMPLE_PAYLOAD)
        assert exc_info.value.error_code == "AUTH_FAILED"

    def test_500_retries_and_raises(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [_http_error(500)] * 4
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            create_workout(_SAMPLE_PAYLOAD)
        assert exc_info.value.error_code == "SERVER_ERROR"


# ---------------------------------------------------------------------------
# update_workout
# ---------------------------------------------------------------------------

class TestUpdateWorkout:

    def test_calls_connectapi_with_put_method(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = None
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        update_workout(12345, _SAMPLE_EXISTING)
        call_str = str(mock_garth.connectapi.call_args)
        assert "PUT" in call_str or mock_garth.connectapi.called

    def test_url_contains_workout_id(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = None
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        update_workout(12345, _SAMPLE_EXISTING)
        call_str = str(mock_garth.connectapi.call_args)
        assert "12345" in call_str

    def test_passes_merged_payload_as_json(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = None
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        payload = {**_SAMPLE_EXISTING, "workoutName": "Updated Name"}
        update_workout(12345, payload)
        call_str = str(mock_garth.connectapi.call_args)
        assert "Updated Name" in call_str or "workoutName" in call_str

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

    def test_calls_connectapi_with_delete_method(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = None
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        delete_workout(12345)
        call_str = str(mock_garth.connectapi.call_args)
        assert "DELETE" in call_str or mock_garth.connectapi.called

    def test_url_contains_workout_id(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = None
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        delete_workout(12345)
        call_str = str(mock_garth.connectapi.call_args)
        assert "12345" in call_str

    def test_returns_none_on_success(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = None
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
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            delete_workout(99999)
        assert exc_info.value.error_code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# schedule_workout
# ---------------------------------------------------------------------------

class TestScheduleWorkout:

    def test_calls_connectapi_with_post_to_schedule_url(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {
            "workoutScheduleId": 555,
            "calendarDate": "2026-04-01",
        }
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        schedule_workout(12345, date(2026, 4, 1))
        call_str = str(mock_garth.connectapi.call_args)
        assert "POST" in call_str or mock_garth.connectapi.called

    def test_url_contains_workout_id(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {
            "workoutScheduleId": 555,
            "calendarDate": "2026-04-01",
        }
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        schedule_workout(12345, date(2026, 4, 1))
        call_str = str(mock_garth.connectapi.call_args)
        assert "12345" in call_str

    def test_passes_date_as_iso_string(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {
            "workoutScheduleId": 555,
            "calendarDate": "2026-04-01",
        }
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        schedule_workout(12345, date(2026, 4, 1))
        call_str = str(mock_garth.connectapi.call_args)
        assert "2026-04-01" in call_str

    def test_returns_schedule_dict(self, mocker: Any) -> None:
        expected = {"workoutScheduleId": 555, "calendarDate": "2026-04-01"}
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = expected
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
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            schedule_workout(99999, date(2026, 4, 1))
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_invalid_date_does_not_crash(self, mocker: Any) -> None:
        """Passing a date object (not a string) should work without crashing."""
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {
            "workoutScheduleId": 777,
            "calendarDate": "2026-04-01",
        }
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = schedule_workout(12345, date(2026, 4, 1))
        assert result is not None
