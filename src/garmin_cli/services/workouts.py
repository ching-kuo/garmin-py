"""Workout scheduling and sending shared by the CLI and MCP front-ends."""

from __future__ import annotations

import unicodedata
from datetime import date
from typing import Any

from garmin_cli.endpoints.devices import get_devices
from garmin_cli.endpoints.workouts import get_workout, schedule_workout
from garmin_cli.exceptions import GarminCliError
from garmin_cli.metrics.registry import (
    CYCLING_TYPE_KEYS,
    LAP_SWIM_TYPE_KEYS,
    OW_SWIM_TYPE_KEYS,
    RUNNING_TYPE_KEYS,
)
from garmin_cli.services.schedule_writes import (
    calendar_rows,
    extract_id,
    find_schedule,
    landed_schedule,
    schedule_ids,
)
from garmin_cli.services.training_plan import is_schedule_row
from garmin_cli.workout_schema import is_positive_id


def schedule_workout_once(workout_id: int, day: date, *, allow_multiple: bool = False) -> dict[str, Any]:
    """Schedule *workout_id* on *day* unless it is already there.

    Returns ``action`` ``"no_op"`` (already scheduled under a known schedule
    id) or ``"scheduled"`` with ``workout_id``, ``workout_schedule_id`` and
    ``date``. After a write, ``workout_schedule_id`` is None when Garmin
    returned no id and it could not be recovered by re-reading the date.
    Raises INVALID_INPUT when this workout is already on the date without a
    schedule id, or (unless *allow_multiple*) when the date holds a different
    workout. Logged activities on the date are ignored.
    """
    # Strict: an incomplete read could hide a schedule and cause a duplicate.
    scheduled = [row for row in calendar_rows(day, day, strict=True) if is_schedule_row(row)]
    existing = find_schedule(scheduled, workout_id)
    if existing is not None:
        return {
            "action": "no_op",
            "workout_id": workout_id,
            "workout_schedule_id": existing["workout_schedule_id"],
            "date": day.isoformat(),
        }
    if any(row.get("workout_id") == workout_id for row in scheduled):
        # Refused even with allow_multiple: it allows a different workout only.
        raise GarminCliError(
            error="This workout is already scheduled on that date but Garmin returned no schedule id.",
            error_code="INVALID_INPUT",
        )
    if scheduled and not allow_multiple:
        raise GarminCliError(
            error="Target date already has a different scheduled workout.",
            error_code="INVALID_INPUT",
        )
    raw = schedule_workout(workout_id, day)
    raw_dict = raw if isinstance(raw, dict) else {}
    schedule_id = extract_id(raw_dict, "workoutScheduleId")
    if schedule_id is None:
        # Garmin occasionally omits the id; recover it from the one new row of
        # this workout (never a pre-existing id). Best-effort: the write was
        # already accepted.
        try:
            schedule_id = landed_schedule(day, None, workout_id, schedule_ids(scheduled))
        except Exception:
            schedule_id = None
    return {
        "action": "scheduled",
        "workout_id": workout_id,
        "workout_schedule_id": schedule_id,
        "date": raw_dict.get("calendarDate") or day.isoformat(),
    }


# Workout sportTypeKey (sub-sports included) -> per-sport device flag; every
# flag name appears on live device rows.
_SPORT_FLAGS = {
    **dict.fromkeys(RUNNING_TYPE_KEYS, "runningWorkoutCapable"),
    **dict.fromkeys(CYCLING_TYPE_KEYS, "cyclingWorkoutCapable"),
    **dict.fromkeys(LAP_SWIM_TYPE_KEYS | OW_SWIM_TYPE_KEYS, "swimWorkoutCapable"),
    "walking": "walkWorkoutCapable",
    "multi_sport": "multisportWorkoutCapable",
    "strength_training": "strengthWorkoutCapable",
    "cardio_training": "cardioWorkoutCapable",
    "hiit": "hiitWorkoutCapable",
    "yoga": "yogaWorkoutCapable",
    "pilates": "pilatesWorkoutCapable",
    "mobility": "mobilityWorkoutCapable",
}


def _invalid(error: str) -> GarminCliError:
    return GarminCliError(error=error, error_code="INVALID_INPUT")


def _printable(value: Any) -> str | None:
    """*value* without control characters (C0, DEL, C1), safe to print; None when nothing is left."""
    if not isinstance(value, str):
        return None
    return "".join(ch for ch in value if unicodedata.category(ch) != "Cc") or None


def prepare_workout_send(workout_id: int, device_id: int | None) -> dict[str, Any]:
    """Read the workout and choose the device to send it to.

    Returns ``workout_id``, ``workout_name``, ``device_id`` and
    ``display_name`` (names stripped of control characters; a nameless
    workout is "Workout <id>"). A missing or empty workout raises NOT_FOUND
    (a non-object SERVER_ERROR) before devices are read. A device qualifies
    when ``workoutCapable`` is true and its flag for the workout's sport
    family is not explicitly false. An explicit *device_id* must be
    registered (else NOT_FOUND) and qualify; without one, the only qualifying
    device is chosen. Otherwise INVALID_INPUT, listing the candidates when
    several qualify.
    """
    workout: Any = get_workout(workout_id)
    if not isinstance(workout, dict):
        raise GarminCliError(error="Garmin returned an unreadable workout.", error_code="SERVER_ERROR")
    if not is_positive_id(workout.get("workoutId")):
        raise GarminCliError(error=f"Workout {workout_id} was not found.", error_code="NOT_FOUND")
    sport_type = workout.get("sportType")
    sport = sport_type.get("sportTypeKey") if isinstance(sport_type, dict) else None
    flag = _SPORT_FLAGS.get(sport) if isinstance(sport, str) else None
    devices = [d for d in get_devices() if isinstance(d, dict) and is_positive_id(d.get("deviceId"))]
    takes_workouts = [d for d in devices if d.get("workoutCapable") is True]
    qualifying = [d for d in takes_workouts if flag is None or d.get(flag) is not False]
    sport_label = f"{sport} " if flag else ""
    if device_id is not None:
        chosen = next((d for d in devices if d["deviceId"] == device_id), None)
        if chosen is None:
            raise GarminCliError(error=f"Device {device_id} is not registered to this account.", error_code="NOT_FOUND")
        if chosen.get("workoutCapable") is not True:
            raise _invalid(f"Device {device_id} cannot receive workouts.")
        if flag is not None and chosen.get(flag) is False:
            raise _invalid(f"Device {device_id} cannot receive {sport_label}workouts.")
    elif len(qualifying) == 1:
        chosen = qualifying[0]
    elif not qualifying:
        raise _invalid(f"No registered device can receive {sport_label}workouts.")
    else:
        candidates = ", ".join(
            f"{d['deviceId']} ({_printable(d.get('displayName')) or 'unnamed device'})" for d in qualifying
        )
        raise _invalid(f"Several devices can receive {sport_label}workouts; choose one by device id: {candidates}.")
    return {
        "workout_id": workout_id,
        "workout_name": _printable(workout.get("workoutName")) or f"Workout {workout_id}",
        "device_id": chosen["deviceId"],
        "display_name": _printable(chosen.get("displayName")),
    }
