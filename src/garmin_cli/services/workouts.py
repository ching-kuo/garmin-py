"""Workout scheduling shared by the CLI and MCP front-ends."""

from __future__ import annotations

from datetime import date
from typing import Any

from garmin_cli.endpoints.workouts import schedule_workout
from garmin_cli.exceptions import GarminCliError
from garmin_cli.services.schedule_writes import (
    calendar_rows,
    extract_id,
    find_schedule,
    landed_schedule,
    schedule_ids,
)
from garmin_cli.services.training_plan import is_schedule_row


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
