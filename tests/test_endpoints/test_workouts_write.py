"""Tests for write operations in garmin_cli.endpoints.workouts."""
from __future__ import annotations

import socket
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.workouts import (
    create_workout,
    delete_workout,
    schedule_workout,
    send_workout_to_device,
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

    def test_500_is_not_retried(self, mocker: Any) -> None:
        # A 5xx POST may still have created the workout; a retry could duplicate it.
        mock_garth = MagicMock()
        mock_garth.create_workout.side_effect = [_http_error(500)] * 4
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            create_workout(_SAMPLE_PAYLOAD)
        assert exc_info.value.error_code == "SERVER_ERROR"
        assert mock_garth.create_workout.call_count == 1

    def test_429_is_retried(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.create_workout.side_effect = [_http_error(429), {"workoutId": 42}]
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        assert create_workout(_SAMPLE_PAYLOAD) == {"workoutId": 42}
        assert mock_garth.create_workout.call_count == 2


# ---------------------------------------------------------------------------
# update_workout
# ---------------------------------------------------------------------------

class TestUpdateWorkout:

    def test_delegates_to_typed_upstream_helper(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.update_workout.return_value = {"workoutId": 12345}
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        result = update_workout(12345, _SAMPLE_EXISTING)

        assert result is None
        mock_garth.update_workout.assert_called_once_with(12345, _SAMPLE_EXISTING)
        mock_garth.connectapi.assert_not_called()

    def test_invalid_workout_id_raises_invalid_input(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            update_workout("not-a-number", _SAMPLE_EXISTING)
        assert exc_info.value.error_code == "INVALID_INPUT"
        mock_garth.update_workout.assert_not_called()

    def test_404_raises_not_found(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.update_workout.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            update_workout(99999, _SAMPLE_EXISTING)
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_403_raises_auth_failed(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.update_workout.side_effect = _http_error(403)
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

    def test_503_is_not_retried(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.schedule_workout.side_effect = _http_error(503)
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            schedule_workout(12345, date(2026, 4, 1))
        assert exc_info.value.error_code == "SERVER_ERROR"
        assert mock_garth.schedule_workout.call_count == 1

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

    def test_404_on_retry_after_server_error_means_already_removed(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.unschedule_workout.side_effect = [_http_error(503), _http_error(404)]
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        assert unschedule_workout(99999) is None
        assert mock_garth.unschedule_workout.call_count == 2

    def test_404_on_retry_after_dns_failure_is_still_not_found(self, mocker: Any) -> None:
        # A DNS failure never reached Garmin, so the later 404 is a genuine miss.
        mock_garth = MagicMock()
        mock_garth.unschedule_workout.side_effect = [socket.gaierror("dns"), _http_error(404)]
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            unschedule_workout(99999)
        assert exc_info.value.error_code == "NOT_FOUND"

    @pytest.mark.parametrize(
        ("side_effect", "landed"),
        [
            ([_http_error(503)] + [_http_error(429)] * 3, True),
            ([_http_error(503), _http_error(401)], True),
            ([_http_error(429)] * 4, False),
        ],
    )
    def test_error_after_a_possibly_processed_attempt_may_have_landed(
        self, mocker: Any, side_effect: list[Exception], landed: bool
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.unschedule_workout.side_effect = side_effect
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            unschedule_workout(99999)
        assert exc_info.value.may_have_landed is landed

    def test_404_on_retry_after_rate_limit_is_still_not_found(self, mocker: Any) -> None:
        # A 429 was not processed, so the later 404 is a genuine miss.
        mock_garth = MagicMock()
        mock_garth.unschedule_workout.side_effect = [_http_error(429), _http_error(404)]
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            unschedule_workout(99999)
        assert exc_info.value.error_code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# send_workout_to_device
# ---------------------------------------------------------------------------

class TestSendWorkoutToDevice:

    @staticmethod
    def _garth(mocker: Any, side_effect: Any = None) -> MagicMock:
        mock_garth = MagicMock()
        mock_garth.send_workout_message.side_effect = side_effect
        mocker.patch("garmin_cli.endpoints.workouts.garth", mock_garth)
        mocker.patch("time.sleep")
        return mock_garth

    def test_delegates_with_validated_ids(self, mocker: Any) -> None:
        mock_garth = self._garth(mocker)

        send_workout_to_device("12345", "Tempo", 678)
        mock_garth.send_workout_message.assert_called_once_with(12345, "Tempo", 678)

    @pytest.mark.parametrize(("workout_id", "device_id"), [("x", 1), (1, 0), (1, True), (1, None)])
    def test_invalid_ids_raise_invalid_input(self, mocker: Any, workout_id: Any, device_id: Any) -> None:
        mock_garth = self._garth(mocker)

        with pytest.raises(GarminCliError) as exc_info:
            send_workout_to_device(workout_id, "Tempo", device_id)
        assert exc_info.value.error_code == "INVALID_INPUT"
        mock_garth.send_workout_message.assert_not_called()

    @pytest.mark.parametrize(
        ("failure", "error_code"),
        [
            (_http_error(503), "SERVER_ERROR"),
            (TimeoutError("read timed out"), "NETWORK_ERROR"),
            (ConnectionResetError("dropped after send"), "NETWORK_ERROR"),
        ],
    )
    def test_5xx_or_network_failure_is_not_retried_and_may_be_queued(
        self, mocker: Any, failure: Exception, error_code: str
    ) -> None:
        # Each accepted POST queues another message; a retry could send it twice.
        mock_garth = self._garth(mocker, failure)

        with pytest.raises(GarminCliError) as exc_info:
            send_workout_to_device(1, "Tempo", 2)
        assert exc_info.value.error_code == error_code
        assert exc_info.value.may_have_landed is True
        assert "may already be queued" in exc_info.value.error
        assert "may already be queued" in str(exc_info.value)
        assert mock_garth.send_workout_message.call_count == 1

    @pytest.mark.parametrize("throttle", [429, 427])
    def test_throttle_is_retried_because_garmin_refused_it(self, mocker: Any, throttle: int) -> None:
        # 427 counts as a throttle repo-wide (exceptions.failure_kind); neither was processed.
        mock_garth = self._garth(mocker, [_http_error(throttle), None])

        send_workout_to_device(1, "Tempo", 2)
        assert mock_garth.send_workout_message.call_count == 2

    @pytest.mark.parametrize(("status", "error_code"), [(401, "AUTH_FAILED"), (404, "NOT_FOUND")])
    def test_rejections_are_classified_without_queue_warning(
        self, mocker: Any, status: int, error_code: str
    ) -> None:
        self._garth(mocker, _http_error(status))

        with pytest.raises(GarminCliError) as exc_info:
            send_workout_to_device(99999, "Tempo", 2)
        assert exc_info.value.error_code == error_code
        assert "queued" not in exc_info.value.error
