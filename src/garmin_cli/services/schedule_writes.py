"""Calendar reads and write verification shared by schedule-writing services."""

from __future__ import annotations

from datetime import date
from typing import Any

from garmin_cli.endpoints.workouts import get_calendar_range
from garmin_cli.exceptions import TRANSIENT_ERROR_CODES, GarminCliError
from garmin_cli.serializers import serialize_calendar_workout
from garmin_cli.workout_schema import is_positive_id

Rows = list[dict[str, Any]]


def calendar_rows(start: date, end: date, *, strict: bool = False) -> Rows:
    """Serialized calendar rows; *strict* raises unless the read is complete."""
    return serialize_calendar_workout({"calendarItems": get_calendar_range(start, end, strict=strict)})


def extract_id(raw: Any, key: str) -> int | None:
    value = raw.get(key) if isinstance(raw, dict) else None
    return value if is_positive_id(value) else None


def has_schedule(rows: Rows, schedule_id: int) -> bool:
    return any(row.get("workout_schedule_id") == schedule_id for row in rows)


def source_gone(schedule_id: int, day: Any) -> bool | None:
    """Whether *schedule_id* is no longer on *day*; None when no complete read is possible."""
    try:
        parsed = day if isinstance(day, date) else date.fromisoformat(day)
        return not has_schedule(calendar_rows(parsed, parsed, strict=True), schedule_id)
    except Exception:
        return None


def schedule_ids(rows: Rows) -> set[Any]:
    return {row.get("workout_schedule_id") for row in rows}


def find_schedule(rows: Rows, workout_id: Any) -> dict[str, Any] | None:
    """The first row scheduling *workout_id* under a known (positive) schedule id."""
    return next(
        (
            row
            for row in rows
            if row.get("workout_id") == workout_id and is_positive_id(row.get("workout_schedule_id"))
        ),
        None,
    )


def landed_schedule(day: date, schedule_id: int | None, workout_id: int, excluded: set[Any]) -> int | None:
    """Re-read *day*: the id of the row a schedule write created, or None when it cannot be proven.

    A returned *schedule_id* must appear with the same workout and date (a stale
    row of a deleted schedule never matches it). Without one, exactly one
    matching row must be new: absent from the pre-write snapshot and not
    claimed by another write of this call (*excluded*). A failed read raises.
    """
    matches = [
        row["workout_schedule_id"]
        for row in calendar_rows(day, day)
        if is_positive_id(row.get("workout_schedule_id"))
        and row.get("workout_id") == workout_id
        and row.get("date") == day.isoformat()
    ]
    if schedule_id is not None:
        return schedule_id if schedule_id in matches else None
    fresh = [match for match in matches if match not in excluded]
    return fresh[0] if len(fresh) == 1 else None


# A write failing with these may still have been applied remotely
# (a rate limit is rejected unprocessed).
_MAY_HAVE_LANDED_CODES = (TRANSIENT_ERROR_CODES - {"RATE_LIMITED"}) | {"INTERNAL_ERROR"}


def may_have_landed(exc: Exception) -> bool:
    """A write that failed this way may still have been applied remotely.

    Includes a final 429/401 after an earlier attempt that Garmin may have processed.
    """
    return not isinstance(exc, GarminCliError) or exc.error_code in _MAY_HAVE_LANDED_CODES or exc.may_have_landed


def error_code(exc: Exception) -> str:
    return exc.error_code if isinstance(exc, GarminCliError) else "INTERNAL_ERROR"
