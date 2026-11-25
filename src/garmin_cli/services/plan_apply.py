"""Live application of training plans, with rollback of this call's writes.

Shared by front-ends; the MCP registrar in :mod:`garmin_cli.mcp_tools.training_plan`
only validates arguments, audits, and calls these functions.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from garmin_cli.endpoints._base import _fan_out
from garmin_cli.endpoints.workouts import (
    create_workout,
    delete_workout,
    get_workout,
    schedule_workout,
    unschedule_workout,
)
from garmin_cli.exceptions import GarminCliError
from garmin_cli.serializers import serialize_workout_detail
from garmin_cli.services.plan_results import write_result
from garmin_cli.services.schedule_writes import (
    Rows,
    calendar_rows,
    error_code,
    extract_id,
    find_schedule,
    has_schedule,
    landed_schedule,
    may_have_landed,
    schedule_ids,
    source_gone,
)
from garmin_cli.services.training_plan import (
    blocking_occupants,
    claims_row,
    entry_source_id,
    is_schedule_row,
    preview_training_plan,
    source_by_schedule,
    vacated_schedule_owners,
)
from garmin_cli.workout_builder import build_garmin_payload
from garmin_cli.workout_schema import is_positive_id


def calendar_with_projections(start: date, end: date) -> tuple[Rows, dict[int, dict[str, Any] | None]]:
    """The calendar rows for the window plus each scheduled workout's write projection.

    Only rows with a known schedule id can satisfy an entry, so only their
    templates are read, concurrently in workout-id order (see ``_fan_out``); a
    template Garmin no longer has gets no projection, and any other failure
    (the first in that order) propagates.
    """
    calendar = calendar_rows(start, end)
    projections: dict[int, dict[str, Any] | None] = {}
    scheduled = sorted({
        row["workout_id"]
        for row in calendar
        if is_schedule_row(row) and is_positive_id(row.get("workout_schedule_id")) and is_positive_id(row["workout_id"])
    })
    for workout_id, raw in zip(scheduled, _fan_out(_template_or_none, scheduled), strict=True):
        if raw is not None:
            projections[workout_id] = serialize_workout_detail(raw)[0].get("write_projection")
    return calendar, projections


def _template_or_none(workout_id: int) -> Any:
    try:
        return get_workout(workout_id)
    except GarminCliError as exc:
        if exc.error_code != "NOT_FOUND":
            raise
        return None


def plan_dates(plan: dict[str, Any]) -> tuple[date, date]:
    """The calendar window a validated plan reads: its range plus every source date."""
    dates = [date.fromisoformat(plan["start_date"]), date.fromisoformat(plan["end_date"])]
    dates.extend(
        date.fromisoformat(entry["expected_source_date"]) for entry in plan["entries"] if "expected_source_date" in entry
    )
    dates.extend(date.fromisoformat(removal["expected_date"]) for removal in plan.get("removals", []))
    return min(dates), max(dates)


def _keep_template(new_templates: list[int], workout_id: int) -> None:
    """Exclude *workout_id* from cleanup: a schedule we cannot identify may reference it."""
    if workout_id in new_templates:
        new_templates.remove(workout_id)


def _compensate_new(new_schedules: list[int], new_templates: list[int], operations: Rows) -> bool:
    """Remove only resources created in this invocation, in reverse order.

    Each cleanup is independent: a failure (of any exception type) is recorded
    and the remaining cleanups still run.
    """
    successful = True
    for schedule_id in reversed(new_schedules):
        try:
            unschedule_workout(schedule_id)
            operations.append({"action": "unschedule", "schedule_id": schedule_id, "state": "compensated"})
        except Exception as exc:
            successful = False
            operations.append(
                {"action": "unschedule", "schedule_id": schedule_id, "state": "unknown", "error_code": error_code(exc)}
            )
    # A template may still be referenced by a schedule whose cleanup failed.
    # Keep all new templates in that case instead of risking a dangling entry.
    if not successful:
        return False
    for workout_id in reversed(new_templates):
        try:
            delete_workout(workout_id)
            operations.append({"action": "delete_template", "workout_id": workout_id, "state": "compensated"})
        except Exception as exc:
            successful = False
            operations.append(
                {"action": "delete_template", "workout_id": workout_id, "state": "unknown", "error_code": error_code(exc)}
            )
    return successful


def _restore_sources(removed_sources: Rows, claimed: set[int], operations: Rows) -> bool:
    """Reschedule removed sources (they get new ids), each proven by its own new row."""
    successful = True
    for source in reversed(removed_sources):
        workout_id, source_date = source.get("workout_id"), source.get("date")
        operation: dict[str, Any] = {
            "action": "restore_source",
            "schedule_id": source.get("workout_schedule_id"),
            "workout_id": workout_id,
            "date": source_date,
            "state": "unknown",
        }
        operations.append(operation)
        try:
            day = date.fromisoformat(str(source_date))  # a bad value fails this op only
            if not isinstance(workout_id, int):
                raise GarminCliError("Removed source has no workout id.", "INTERNAL_ERROR")
            before = schedule_ids(calendar_rows(day, day))
            new_id = extract_id(schedule_workout(workout_id, day), "workoutScheduleId")
            restored_id = landed_schedule(day, new_id, workout_id, before | claimed)
            if restored_id is not None:
                claimed.add(restored_id)
                operation.update(state="compensated", restored_schedule_id=restored_id)
        except Exception as exc:
            operation["error_code"] = error_code(exc)
        successful = successful and operation["state"] == "compensated"
    return successful


def apply_training_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Apply a validated plan after live rechecks, compensating on any failure."""
    start, end = plan_dates(plan)
    calendar, projections = calendar_with_projections(start, end)
    preview = preview_training_plan(plan, calendar, projections)
    if not preview["complete"]:
        return {**preview, "outcome": "partial"}
    operations: Rows = []
    conflicts: list[dict[str, str]] = []
    new_schedules: list[int] = []
    new_templates: list[int] = []
    claimed: set[int] = set()  # schedule ids attributed to this call's writes
    removed_sources: Rows = []
    # (schedule id, snapshot row, conflict owner) of sources removed last.
    source_removals: list[tuple[int, dict[str, Any], dict[str, str]]] = []
    schedules = source_by_schedule(calendar)
    vacated = vacated_schedule_owners(plan, schedules)
    keep_by_entry = {
        operation["entry_id"]: operation
        for operation in preview["operations"]
        if operation.get("action") == "keep" and isinstance(operation.get("entry_id"), str)
    }
    # Set when a write happened whose identifier or effect is unknown: it can
    # never be compensated, so a later failure must report `unknown`.
    unidentified_write = False

    def remove_source(schedule_id: int, source: dict[str, Any], *, last: bool = False) -> None:
        """Unschedule a pre-existing schedule once, recording it for rollback.

        A failed delete that may have landed is rechecked with a complete read:
        if it did land it is recorded for rollback, and as the plan's last step
        it counts as done.
        """
        nonlocal unidentified_write
        if has_schedule(removed_sources, schedule_id):
            return
        landed: Exception | None = None
        try:
            unschedule_workout(schedule_id)
        except Exception as exc:
            if not may_have_landed(exc):
                raise
            gone = source_gone(schedule_id, source["date"])
            if gone is None:
                unidentified_write = True
                operations.append({"action": "unschedule", "schedule_id": schedule_id, "state": "unknown"})
                raise exc from None
            if not gone:
                raise
            landed = exc
        removed_sources.append(source)
        operations.append({"action": "unschedule", "schedule_id": schedule_id, "state": "applied"})
        if landed is not None and not last:
            raise landed

    try:
        for entry in plan["entries"]:
            entry_id = entry["entry_id"]
            source_id = entry_source_id(entry)
            keep = keep_by_entry.get(entry_id)
            workout_id = keep.get("workout_id") if keep is not None else entry.get("workout_id")
            destination_schedule_id = keep.get("workout_schedule_id") if keep is not None else None
            if keep is not None:
                operations.append({**keep, "state": "no_op"})
            elif "workout" in entry:
                payload = build_garmin_payload(entry["workout"])
                try:
                    raw = create_workout(payload)
                except Exception as exc:
                    if may_have_landed(exc):
                        unidentified_write = True
                        operations.append({"entry_id": entry_id, "action": "create_template", "state": "unknown"})
                    raise
                workout_id = extract_id(raw, "workoutId")
                if workout_id is None:
                    unidentified_write = True
                    operations.append({"entry_id": entry_id, "action": "create_template", "state": "unknown"})
                    raise GarminCliError("Workout creation returned no identifier.", "SERVER_ERROR")
                new_templates.append(workout_id)
                operations.append(
                    {"entry_id": entry_id, "action": "create_template", "workout_id": workout_id, "state": "applied"}
                )
            if not isinstance(workout_id, int):
                raise GarminCliError("Workout identifier is unavailable.", "INTERNAL_ERROR")
            if keep is None:
                destination = date.fromisoformat(entry["date"])
                # Occupants another entry or removal vacates neither satisfy
                # nor block this entry; they are removed before the write.
                live_rows = calendar_rows(destination, destination)
                destination_rows: Rows = []
                vacated_rows: Rows = []
                for row in live_rows:
                    (destination_rows if claims_row(vacated, row, entry_id) else vacated_rows).append(row)
                existing = find_schedule(destination_rows, workout_id)
                if existing is not None:
                    destination_schedule_id = existing.get("workout_schedule_id")
                    operations.append(
                        {
                            "entry_id": entry_id,
                            "action": "schedule",
                            "date": entry["date"],
                            "workout_id": workout_id,
                            "state": "no_op",
                            "workout_schedule_id": destination_schedule_id,
                        }
                    )
                else:
                    # An occupied destination is tolerated only when every
                    # occupant is the entry's own source (same-date replace)
                    # or vacated by the plan; a move/replace flag must not
                    # unlock unrelated occupants.
                    if blocking_occupants(destination_rows, source_id):
                        raise GarminCliError("Destination date has a scheduled workout.", "INVALID_INPUT")
                    # Vacate only schedules still on the date the plan verified.
                    if any(row.get("date") != schedules[row["workout_schedule_id"]].get("date") for row in vacated_rows):
                        conflicts.append({"entry_id": entry_id, "reason": "source_schedule_changed"})
                        raise GarminCliError("A schedule this plan vacates has moved.", "INVALID_INPUT")
                    for row in vacated_rows:
                        remove_source(row["workout_schedule_id"], row)
                    try:
                        raw_schedule = schedule_workout(workout_id, destination)
                    except Exception as exc:
                        if may_have_landed(exc):
                            unidentified_write = True
                            _keep_template(new_templates, workout_id)
                            operations.append(
                                {
                                    "entry_id": entry_id,
                                    "action": "schedule",
                                    "date": entry["date"],
                                    "workout_id": workout_id,
                                    "state": "unknown",
                                }
                            )
                        raise
                    # Compensation only ever touches an id our own write returned.
                    schedule_id = extract_id(raw_schedule, "workoutScheduleId")
                    if schedule_id is not None:
                        new_schedules.append(schedule_id)
                    else:
                        unidentified_write = True
                        _keep_template(new_templates, workout_id)
                    destination_schedule_id = landed_schedule(
                        destination, schedule_id, workout_id, schedule_ids(live_rows) | claimed
                    )
                    if destination_schedule_id is None:
                        raise GarminCliError("New schedule could not be verified.", "SERVER_ERROR")
                    claimed.add(destination_schedule_id)
                    operations.append(
                        {
                            "entry_id": entry_id,
                            "action": "schedule",
                            "date": entry["date"],
                            "workout_id": workout_id,
                            "workout_schedule_id": destination_schedule_id,
                            "state": "verified",
                        }
                    )
            if source_id is not None and source_id != destination_schedule_id:
                if not is_positive_id(destination_schedule_id):
                    # Never remove a source without a verified destination.
                    raise GarminCliError("Destination schedule could not be verified.", "SERVER_ERROR")
                # Preview (run on this same calendar snapshot) already turned a
                # moved source into a conflict; an absent one means an earlier
                # apply finished the move, so there is nothing left to remove.
                source = schedules.get(source_id)
                if source is not None and source.get("date") == entry["expected_source_date"]:
                    source_removals.append((source_id, source, {"entry_id": entry_id}))
        for removal in plan.get("removals", []):
            source = schedules.get(removal["schedule_id"])
            if source is None or source.get("date") != removal["expected_date"]:
                operations.append(
                    {"action": "unschedule", "source_schedule_id": removal["schedule_id"], "state": "no_op"}
                )
                continue
            source_removals.append((removal["schedule_id"], source, {"schedule_id": str(removal["schedule_id"])}))
        # Sources an entry already vacated are done; the last of the rest is the plan's final step.
        pending = [removal for removal in source_removals if not has_schedule(removed_sources, removal[0])]
        for index, (schedule_id, source, owner) in enumerate(pending):
            # The snapshot may be stale by now: delete only where the plan saw it.
            # A failed read raises, so nothing is deleted and compensation runs.
            day = date.fromisoformat(source["date"])
            if not has_schedule(calendar_rows(day, day, strict=True), schedule_id):
                conflicts.append({**owner, "reason": "source_schedule_changed"})
                raise GarminCliError("A source schedule moved before its removal.", "INVALID_INPUT")
            remove_source(schedule_id, source, last=index == len(pending) - 1)
        performed_write = any(operation.get("state") in {"applied", "verified"} for operation in operations)
        return write_result("complete" if performed_write else "no_op", operations, complete=True)
    except Exception as exc:
        # Any failure mid-apply (including non-Garmin bugs) must attempt
        # compensation; leaving half a destructive plan applied is worse than
        # reporting an internal error with a restored calendar.
        code = error_code(exc)
        # New schedules go first, so a leftover one of the same workout cannot
        # pass for a restored source.
        cleaned = _compensate_new(new_schedules, new_templates, operations)
        restored = _restore_sources(removed_sources, claimed, operations)
        outcome = "compensated" if cleaned and restored and not unidentified_write else "unknown"
        operations.append({"action": "apply", "state": "failed", "error_code": code})
        errors = [{"error_code": code, "message": "Plan application did not complete."}]
        return write_result(outcome, operations, errors=errors, conflicts=conflicts)
