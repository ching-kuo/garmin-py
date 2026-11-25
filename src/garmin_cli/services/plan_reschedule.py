"""Source-verified moves of one scheduled workout, destination first."""

from __future__ import annotations

from datetime import date
from typing import Any

from garmin_cli.endpoints.workouts import schedule_workout, unschedule_workout
from garmin_cli.services.plan_results import write_result
from garmin_cli.services.schedule_writes import (
    calendar_rows,
    error_code,
    extract_id,
    landed_schedule,
    may_have_landed,
    schedule_ids,
    source_gone,
)
from garmin_cli.services.training_plan import is_schedule_row
from garmin_cli.workout_schema import is_positive_id

Rows = list[dict[str, Any]]


def _conflict(reason: str) -> dict[str, Any]:
    return write_result("partial", conflicts=[{"reason": reason}])


def _failed_source_unschedule(schedule_id: int, exc: Exception) -> tuple[dict[str, Any], Rows]:
    code = error_code(exc)
    failed_op = {"action": "unschedule", "schedule_id": schedule_id, "state": "failed", "error_code": code}
    return failed_op, [{"error_code": code, "message": "Source unschedule did not complete."}]


def _source_gone_result(
    schedule_id: int, source_date: date, done_op: dict[str, Any], failed_op: dict[str, Any], errors: Rows
) -> dict[str, Any] | None:
    """After a failed source delete: complete if it landed, unknown if unreadable, None if it remains."""
    gone = source_gone(schedule_id, source_date)
    if gone is None:
        return write_result("unknown", [failed_op], errors=errors)
    if gone:
        # Desired end state reached: destination verified, source gone.
        return write_result("complete", [done_op, failed_op], complete=True)
    return None


def _undo_destination(new_schedule_id: int, operations: Rows, errors: Rows) -> dict[str, Any]:
    """Remove the destination this call created, leaving the source in place."""
    try:
        unschedule_workout(new_schedule_id)
    except Exception as exc:
        unknown_op = {"action": "schedule", "state": "unknown", "schedule_id": new_schedule_id, "error_code": error_code(exc)}
        return write_result("unknown", [*operations, unknown_op], errors=errors)
    compensated_op = {"action": "schedule", "state": "compensated", "schedule_id": new_schedule_id}
    return write_result("compensated", [*operations, compensated_op], errors=errors)


def reschedule_schedule(schedule_id: int, destination: date, expected_date: str) -> dict[str, Any]:
    """Move a schedule found on *expected_date* destination-first, then remove its source."""
    source_date = date.fromisoformat(expected_date)
    source = next(
        (
            row
            for row in calendar_rows(source_date, source_date)
            if row.get("workout_schedule_id") == schedule_id and row.get("date") == source_date.isoformat()
        ),
        None,
    )
    if source is None or not isinstance(source.get("workout_id"), int):
        return _conflict("source_schedule_changed")
    if source_date == destination:
        return write_result("no_op", [{"action": "move", "state": "no_op", "schedule_id": schedule_id}], complete=True)
    workout_id = source["workout_id"]
    destination_rows = calendar_rows(destination, destination)
    # Logged activities on the date carry workout ids but are not schedules.
    destination_schedules = [row for row in destination_rows if is_schedule_row(row)]
    if any(row.get("workout_id") != workout_id for row in destination_schedules):
        return _conflict("destination_occupied")
    existing = next(iter(destination_schedules), None)
    if existing is not None:
        existing_schedule_id = existing.get("workout_schedule_id")
        if not is_positive_id(existing_schedule_id):
            return _conflict("destination_schedule_id_unavailable")
        verified_op = {"action": "move", "state": "verified", "schedule_id": existing_schedule_id}
        try:
            unschedule_workout(schedule_id)
        except Exception as exc:
            failed_op, errors = _failed_source_unschedule(schedule_id, exc)
            if may_have_landed(exc):
                # The failed delete may still have removed the source remotely.
                settled = _source_gone_result(schedule_id, source_date, verified_op, failed_op, errors)
                if settled is not None:
                    return settled
            return write_result("partial", [failed_op], errors=errors)
        return write_result("complete", [verified_op], complete=True)
    try:
        raw = schedule_workout(workout_id, destination)
    except Exception as exc:
        if not may_have_landed(exc):
            raise
        return write_result("unknown", [{"action": "schedule", "state": "unknown", "error_code": error_code(exc)}])
    new_schedule_id = extract_id(raw, "workoutScheduleId")
    try:
        reported_id = landed_schedule(destination, new_schedule_id, workout_id, schedule_ids(destination_rows))
    except Exception as exc:
        # The source stays: the destination was never verified.
        errors = [{"error_code": error_code(exc), "message": "New schedule could not be verified."}]
        if new_schedule_id is None:
            unknown_op = {"action": "schedule", "state": "unknown", "date": destination.isoformat()}
            return write_result("unknown", [unknown_op], errors=errors)
        return _undo_destination(new_schedule_id, [], errors)
    if reported_id is None:
        if new_schedule_id is None:
            unavailable = [{"reason": "destination_schedule_id_unavailable"}]
            return write_result("unknown", [{"action": "schedule", "state": "unknown"}], conflicts=unavailable)
        return _undo_destination(new_schedule_id, [], [])
    moved_op = {"action": "move", "state": "verified", "schedule_id": reported_id}
    try:
        unschedule_workout(schedule_id)
    except Exception as exc:
        failed_op, errors = _failed_source_unschedule(schedule_id, exc)
        # The failed delete may still have removed the source remotely;
        # a complete re-read decides between success and compensation.
        settled = _source_gone_result(schedule_id, source_date, moved_op, failed_op, errors)
        if settled is not None:
            return settled
        if new_schedule_id is None:
            # The verified destination row cannot be proven ours; leave it.
            return write_result("unknown", [failed_op], errors=errors)
        return _undo_destination(new_schedule_id, [failed_op], errors)
    return write_result("complete", [moved_op], complete=True)
