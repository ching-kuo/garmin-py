"""Tests for the shared idempotent workout scheduling service."""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from garmin_cli.exceptions import GarminCliError
from garmin_cli.services.workouts import prepare_workout_send, schedule_workout_once
from tests.helpers import EDGE, EDGE_1040, FENIX, HRM, workout

_DAY = date(2026, 4, 1)
_CALENDAR = "garmin_cli.services.schedule_writes.get_calendar_range"
_SCHEDULE = "garmin_cli.services.workouts.schedule_workout"


def _activity(workout_id: int) -> dict[str, Any]:
    return {"itemType": "activity", "id": 777, "workoutId": workout_id, "date": "2026-04-01"}


def _workout(workout_id: int, schedule_id: int | None = 555) -> dict[str, Any]:
    return {"itemType": "workout", "id": schedule_id, "workoutId": workout_id, "date": "2026-04-01"}


@pytest.mark.parametrize("logged_workout_id", [12345, 999])
def test_a_logged_activity_neither_satisfies_nor_blocks_the_date(mocker: Any, logged_workout_id: int) -> None:
    mocker.patch(_CALENDAR, return_value=[_activity(logged_workout_id)])
    schedule = mocker.patch(_SCHEDULE, return_value={"workoutScheduleId": 555, "calendarDate": "2026-04-01"})

    result = schedule_workout_once(12345, _DAY)

    schedule.assert_called_once_with(12345, _DAY)
    assert result == {"action": "scheduled", "workout_id": 12345, "workout_schedule_id": 555, "date": "2026-04-01"}


@pytest.mark.parametrize("allow_multiple", [False, True])
def test_same_workout_without_schedule_id_is_refused(mocker: Any, allow_multiple: bool) -> None:
    mocker.patch(_CALENDAR, return_value=[_workout(12345, schedule_id=None)])
    schedule = mocker.patch(_SCHEDULE)

    with pytest.raises(GarminCliError) as excinfo:
        schedule_workout_once(12345, _DAY, allow_multiple=allow_multiple)

    assert excinfo.value.error_code == "INVALID_INPUT"
    assert "already scheduled on that date but Garmin returned no schedule id" in excinfo.value.error
    schedule.assert_not_called()


def test_recovery_never_returns_a_pre_existing_schedule_id(mocker: Any) -> None:
    # The re-read attributes the snapshot's schedule 444 to this workout; it is not new.
    mocker.patch(_CALENDAR, side_effect=[[_workout(999, 444)], [_workout(12345, 444)]])
    mocker.patch(_SCHEDULE, return_value={})

    result = schedule_workout_once(12345, _DAY, allow_multiple=True)

    assert result["workout_schedule_id"] is None


def test_allow_multiple_schedules_next_to_a_different_workout(mocker: Any) -> None:
    mocker.patch(_CALENDAR, return_value=[_workout(999)])
    schedule = mocker.patch(_SCHEDULE, return_value={"workoutScheduleId": 556})

    result = schedule_workout_once(12345, _DAY, allow_multiple=True)

    schedule.assert_called_once()
    assert result["action"] == "scheduled"
    assert result["workout_schedule_id"] == 556


def test_pre_write_read_is_strict_and_a_failure_prevents_the_write(mocker: Any) -> None:
    calendar = mocker.patch(_CALENDAR, side_effect=GarminCliError("lookup failed", "SERVER_ERROR"))
    schedule = mocker.patch(_SCHEDULE)

    with pytest.raises(GarminCliError):
        schedule_workout_once(12345, _DAY)

    calendar.assert_called_once_with(_DAY, _DAY, strict=True)
    schedule.assert_not_called()


def test_non_positive_returned_id_is_recovered_from_the_new_row(mocker: Any) -> None:
    mocker.patch(_CALENDAR, side_effect=[[_workout(999, schedule_id=444)], [_workout(999, 444), _workout(12345, 557)]])
    mocker.patch(_SCHEDULE, return_value={"workoutScheduleId": 0})

    result = schedule_workout_once(12345, _DAY, allow_multiple=True)

    assert result["workout_schedule_id"] == 557


def test_failed_recovery_read_still_reports_the_accepted_write(mocker: Any) -> None:
    mocker.patch(_CALENDAR, side_effect=[[], GarminCliError("unreachable", "NETWORK_ERROR")])
    mocker.patch(_SCHEDULE, return_value={})

    result = schedule_workout_once(12345, _DAY)

    assert result == {"action": "scheduled", "workout_id": 12345, "workout_schedule_id": None, "date": "2026-04-01"}


def _send_target(mocker: Any, devices: list[dict[str, Any]], sport: str = "running") -> None:
    mocker.patch("garmin_cli.services.workouts.get_workout", return_value=workout(sport))
    mocker.patch("garmin_cli.services.workouts.get_devices", return_value=devices)


@pytest.mark.parametrize(
    ("devices", "sport", "device_id", "chosen"),
    [
        ([FENIX, EDGE, HRM], "running", None, FENIX),  # the Edge cannot take a run
        ([FENIX, EDGE, HRM], "cycling", 22, EDGE),
        ([EDGE, {**FENIX, "deviceId": True}], "cycling", None, EDGE),  # a bool id is no device
        ([{**FENIX, "runningWorkoutCapable": None}], "running", None, FENIX),  # only an explicit False excludes
        ([FENIX, EDGE], "yoga_flow", 22, EDGE),  # unmapped sport: workoutCapable alone decides
    ],
)
def test_prepare_workout_send_picks_a_device_for_the_sport(
    mocker: Any, devices: list[dict[str, Any]], sport: str, device_id: int | None, chosen: dict[str, Any]
) -> None:
    _send_target(mocker, devices, sport)

    assert prepare_workout_send(123, device_id) == {
        "workout_id": 123, "workout_name": "Tempo",
        "device_id": chosen["deviceId"], "display_name": chosen["displayName"],
    }


@pytest.mark.parametrize(
    ("devices", "sport", "device_id", "error_code", "message"),
    [
        ([FENIX, EDGE, EDGE_1040, HRM], "cycling", None, "INVALID_INPUT", "11 (fenix 8), 22 (Edge 850), 23 (Edge 1040)"),
        ([EDGE, HRM], "running", None, "INVALID_INPUT", "No registered device can receive running workouts"),
        ([FENIX, EDGE], "running", 22, "INVALID_INPUT", "Device 22 cannot receive running workouts"),
        ([FENIX, HRM], "running", 33, "INVALID_INPUT", "Device 33 cannot receive workouts"),
        ([FENIX], "running", 99, "NOT_FOUND", "not registered"),
    ],
)
def test_prepare_workout_send_refuses_ambiguous_or_unusable_targets(
    mocker: Any, devices: list[dict[str, Any]], sport: str, device_id: int | None, error_code: str, message: str
) -> None:
    _send_target(mocker, devices, sport)

    with pytest.raises(GarminCliError) as exc_info:
        prepare_workout_send(123, device_id)
    assert exc_info.value.error_code == error_code
    assert message in exc_info.value.error


def test_prepare_workout_send_fails_for_a_missing_workout_before_reading_devices(mocker: Any) -> None:
    mocker.patch("garmin_cli.services.workouts.get_workout", side_effect=GarminCliError("Not found", "NOT_FOUND"))
    devices = mocker.patch("garmin_cli.services.workouts.get_devices")

    with pytest.raises(GarminCliError, match="Not found"):
        prepare_workout_send(123, None)
    devices.assert_not_called()


def test_a_sub_sport_uses_its_parent_sport_flag(mocker: Any) -> None:
    _send_target(mocker, [FENIX, EDGE], "trail_running")
    assert prepare_workout_send(123, None)["device_id"] == 11

    with pytest.raises(GarminCliError, match="Device 22 cannot receive trail_running workouts"):
        prepare_workout_send(123, 22)


@pytest.mark.parametrize(("payload", "error_code"), [({}, "NOT_FOUND"), ({"workoutName": "x"}, "NOT_FOUND"), ([], "SERVER_ERROR")])
def test_an_empty_or_malformed_workout_fails_before_reading_devices(
    mocker: Any, payload: Any, error_code: str
) -> None:
    mocker.patch("garmin_cli.services.workouts.get_workout", return_value=payload)
    devices = mocker.patch("garmin_cli.services.workouts.get_devices")

    with pytest.raises(GarminCliError) as exc_info:
        prepare_workout_send(123, None)
    assert exc_info.value.error_code == error_code
    devices.assert_not_called()


def test_names_are_made_safe_to_print(mocker: Any) -> None:
    evil = {**FENIX, "displayName": "\x1b[2K\rEvil\x9b"}
    unnamed = {**EDGE, "displayName": None, "runningWorkoutCapable": True}
    mocker.patch(
        "garmin_cli.services.workouts.get_workout",
        return_value={"workoutId": 123, "workoutName": None, "sportType": {"sportTypeKey": "running"}},
    )
    mocker.patch("garmin_cli.services.workouts.get_devices", return_value=[evil, unnamed])

    with pytest.raises(GarminCliError) as exc_info:
        prepare_workout_send(123, None)
    assert "11 ([2KEvil), 22 (unnamed device)" in exc_info.value.error

    assert prepare_workout_send(123, 11) == {
        "workout_id": 123, "workout_name": "Workout 123", "device_id": 11, "display_name": "[2KEvil",
    }
