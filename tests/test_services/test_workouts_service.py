"""Tests for the shared idempotent workout scheduling service."""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from garmin_cli.exceptions import GarminCliError
from garmin_cli.services.workouts import schedule_workout_once

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
