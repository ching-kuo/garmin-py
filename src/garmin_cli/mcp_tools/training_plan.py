"""Stateless preview and destructive application of structured training plans."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from garmin_cli.config import CliConfig
from garmin_cli.endpoints.workouts import (
    create_workout,
    delete_workout,
    get_calendar_range,
    get_workout,
    schedule_workout,
    unschedule_workout,
)
from garmin_cli.exceptions import TRANSIENT_ERROR_CODES, GarminCliError
from garmin_cli.mcp_tools._shared import _authenticated, _parse_date
from garmin_cli.serializers import serialize_calendar_workout, serialize_workout_detail
from garmin_cli.services.training_plan import (
    blocking_occupants,
    claims_row,
    entry_source_id,
    preview_training_plan,
    source_by_schedule,
    vacated_schedule_owners,
    validate_training_plan,
)
from garmin_cli.workout_builder import build_garmin_payload
from garmin_cli.workout_schema import is_positive_id

Rows = list[dict[str, Any]]


def _extract_id(raw: Any, key: str) -> int | None:
    value = raw.get(key) if isinstance(raw, dict) else None
    return value if is_positive_id(value) else None


def _calendar(start: date, end: date, *, strict: bool = False) -> Rows:
    return serialize_calendar_workout({"calendarItems": get_calendar_range(start, end, strict=strict)})


def _calendar_with_projections(start: date, end: date) -> tuple[Rows, dict[int, dict[str, Any] | None]]:
    calendar = _calendar(start, end)
    projections: dict[int, dict[str, Any] | None] = {}
    for workout_id in {row.get("workout_id") for row in calendar}:
        if isinstance(workout_id, int) and not isinstance(workout_id, bool):
            detail = serialize_workout_detail(get_workout(workout_id))[0]
            projections[workout_id] = detail.get("write_projection")
    return calendar, projections


def _plan_dates(plan: dict[str, Any]) -> tuple[date, date]:
    dates = [date.fromisoformat(plan["start_date"]), date.fromisoformat(plan["end_date"])]
    dates.extend(
        date.fromisoformat(entry["expected_source_date"]) for entry in plan["entries"] if "expected_source_date" in entry
    )
    dates.extend(date.fromisoformat(removal["expected_date"]) for removal in plan.get("removals", []))
    return min(dates), max(dates)


def _invalid_plan(plan: Any) -> dict[str, Any] | None:
    errors = validate_training_plan(plan)
    if errors:
        return {
            "complete": False,
            "outcome": "no_op",
            "operations": [],
            "errors": [{"error_code": "INVALID_INPUT", "message": error} for error in errors],
            "conflicts": [],
            "summary": {},
        }
    return None


def _source_schedule(calendar: Rows, schedule_id: int, expected_date: str) -> dict[str, Any] | None:
    return next(
        (row for row in calendar if row.get("workout_schedule_id") == schedule_id and row.get("date") == expected_date),
        None,
    )


def _has_schedule(rows: Rows, schedule_id: int) -> bool:
    return any(row.get("workout_schedule_id") == schedule_id for row in rows)


def _still_scheduled(schedule_id: int, day: date) -> bool:
    """Whether *schedule_id* is on *day*; raises unless the calendar read is complete."""
    return _has_schedule(_calendar(day, day, strict=True), schedule_id)


def _schedule_ids(rows: Rows) -> set[Any]:
    return {row.get("workout_schedule_id") for row in rows}


def _landed_schedule(rows: Rows, schedule_id: int | None, workout_id: int, day: str, excluded: set[Any]) -> int | None:
    """The id of the row a schedule write created, or None when it cannot be proven.

    A returned *schedule_id* must appear with the same workout and date (a stale
    row of a deleted schedule never matches it). Without one, exactly one
    matching row must be new: absent from the pre-write snapshot and not
    claimed by another write of this call (*excluded*).
    """
    matches = [
        row["workout_schedule_id"]
        for row in rows
        if is_positive_id(row.get("workout_schedule_id")) and row.get("workout_id") == workout_id and row.get("date") == day
    ]
    if schedule_id is not None:
        return schedule_id if schedule_id in matches else None
    fresh = [match for match in matches if match not in excluded]
    return fresh[0] if len(fresh) == 1 else None


# A write failing with these may still have been applied remotely
# (a rate limit is rejected unprocessed).
_MAY_HAVE_LANDED_CODES = (TRANSIENT_ERROR_CODES - {"RATE_LIMITED"}) | {"INTERNAL_ERROR"}


def _may_have_landed(exc: Exception) -> bool:
    """A write that failed this way may still have been applied remotely.

    Includes a final 429/401 after an earlier attempt that Garmin may have processed.
    """
    return not isinstance(exc, GarminCliError) or exc.error_code in _MAY_HAVE_LANDED_CODES or exc.may_have_landed


def _keep_template(new_templates: list[int], workout_id: int) -> None:
    """Exclude *workout_id* from cleanup: a schedule we cannot identify may reference it."""
    if workout_id in new_templates:
        new_templates.remove(workout_id)


def _result(
    outcome: str,
    operations: Iterable[dict[str, Any]] = (),
    *,
    complete: bool = False,
    errors: Iterable[dict[str, Any]] = (),
    conflicts: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "complete": complete,
        "outcome": outcome,
        "operations": list(operations),
        "errors": list(errors),
        "conflicts": list(conflicts),
    }


def _conflict(reason: str) -> dict[str, Any]:
    return _result("partial", conflicts=[{"reason": reason}])


def _error_code(exc: Exception) -> str:
    return exc.error_code if isinstance(exc, GarminCliError) else "INTERNAL_ERROR"


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
                {"action": "unschedule", "schedule_id": schedule_id, "state": "unknown", "error_code": _error_code(exc)}
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
                {"action": "delete_template", "workout_id": workout_id, "state": "unknown", "error_code": _error_code(exc)}
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
            before = _schedule_ids(_calendar(day, day))
            new_id = _extract_id(schedule_workout(workout_id, day), "workoutScheduleId")
            restored_id = _landed_schedule(_calendar(day, day), new_id, workout_id, day.isoformat(), before | claimed)
            if restored_id is not None:
                claimed.add(restored_id)
                operation.update(state="compensated", restored_schedule_id=restored_id)
        except Exception as exc:
            operation["error_code"] = _error_code(exc)
        successful = successful and operation["state"] == "compensated"
    return successful


def _apply_plan(plan: dict[str, Any]) -> dict[str, Any]:
    start, end = _plan_dates(plan)
    calendar, projections = _calendar_with_projections(start, end)
    preview = preview_training_plan(plan, calendar, projections)
    if not preview["complete"]:
        return {**preview, "outcome": "partial"}
    operations: Rows = []
    conflicts: list[dict[str, str]] = []
    new_schedules: list[int] = []
    new_templates: list[int] = []
    claimed: set[int] = set()  # schedule ids attributed to this call's writes
    removed_sources: Rows = []
    source_removals: list[tuple[int, dict[str, Any]]] = []
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
        if _has_schedule(removed_sources, schedule_id):
            return
        landed: Exception | None = None
        try:
            unschedule_workout(schedule_id)
        except Exception as exc:
            if not _may_have_landed(exc):
                raise
            try:
                remains = _still_scheduled(schedule_id, date.fromisoformat(source["date"]))
            except Exception:
                unidentified_write = True
                operations.append({"action": "unschedule", "schedule_id": schedule_id, "state": "unknown"})
                raise exc from None
            if remains:
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
                    if _may_have_landed(exc):
                        unidentified_write = True
                        operations.append({"entry_id": entry_id, "action": "create_template", "state": "unknown"})
                    raise
                workout_id = _extract_id(raw, "workoutId")
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
                live_rows = _calendar(destination, destination)
                destination_rows: Rows = []
                vacated_rows: Rows = []
                for row in live_rows:
                    (destination_rows if claims_row(vacated, row, entry_id) else vacated_rows).append(row)
                existing = next((row for row in destination_rows if row.get("workout_id") == workout_id), None)
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
                        if _may_have_landed(exc):
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
                    schedule_id = _extract_id(raw_schedule, "workoutScheduleId")
                    if schedule_id is not None:
                        new_schedules.append(schedule_id)
                    else:
                        unidentified_write = True
                        _keep_template(new_templates, workout_id)
                    destination_schedule_id = _landed_schedule(
                        _calendar(destination, destination),
                        schedule_id,
                        workout_id,
                        entry["date"],
                        _schedule_ids(live_rows) | claimed,
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
                # Preview (run on this same calendar snapshot) already turned a
                # moved source into a conflict; an absent one means an earlier
                # apply finished the move, so there is nothing left to remove.
                source = _source_schedule(calendar, source_id, entry["expected_source_date"])
                if source is not None:
                    source_removals.append((source_id, source))
        for removal in plan.get("removals", []):
            source = _source_schedule(calendar, removal["schedule_id"], removal["expected_date"])
            if source is None:
                operations.append(
                    {"action": "unschedule", "source_schedule_id": removal["schedule_id"], "state": "no_op"}
                )
                continue
            source_removals.append((removal["schedule_id"], source))
        for index, (schedule_id, source) in enumerate(source_removals):
            remove_source(schedule_id, source, last=index == len(source_removals) - 1)
        performed_write = any(operation.get("state") in {"applied", "verified"} for operation in operations)
        return _result("complete" if performed_write else "no_op", operations, complete=True)
    except Exception as exc:
        # Any failure mid-apply (including non-Garmin bugs) must attempt
        # compensation; leaving half a destructive plan applied is worse than
        # reporting an internal error with a restored calendar.
        error_code = _error_code(exc)
        # New schedules go first, so a leftover one of the same workout cannot
        # pass for a restored source.
        cleaned = _compensate_new(new_schedules, new_templates, operations)
        restored = _restore_sources(removed_sources, claimed, operations)
        outcome = "compensated" if cleaned and restored and not unidentified_write else "unknown"
        operations.append({"action": "apply", "state": "failed", "error_code": error_code})
        errors = [{"error_code": error_code, "message": "Plan application did not complete."}]
        return _result(outcome, operations, errors=errors, conflicts=conflicts)


def register_training_plan_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register state-free plan preview, apply, and source-verified moves."""

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def training_plan_preview(plan: dict[str, Any]) -> dict[str, Any]:
        """Read live state and return a normalized plan diff without writing."""
        invalid = _invalid_plan(plan)
        if invalid is not None:
            return invalid
        start, end = _plan_dates(plan)
        return _authenticated(
            config,
            lambda: preview_training_plan(plan, *_calendar_with_projections(start, end)),
        )

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def training_plan_apply(plan: dict[str, Any]) -> dict[str, Any]:
        """Apply a validated plan after live rechecks; no confirmation boolean is accepted."""
        invalid = _invalid_plan(plan)
        if invalid is not None:
            return invalid
        return _authenticated(config, lambda: _apply_plan(plan))

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def training_plan_reschedule(schedule_id: int, new_date: str, expected_date: str) -> dict[str, Any]:
        """Move a known schedule destination-first, then remove its source.

        ``expected_date`` is required because Garmin exposes no direct lookup by
        schedule ID; it lets the tool verify that the source was not changed.
        A new date that already holds a different workout returns a
        ``destination_occupied`` conflict without writing.
        """
        if not is_positive_id(schedule_id):
            raise ToolError("schedule_id must be a positive integer")
        destination = _parse_date(new_date, "new_date")
        source_date = _parse_date(expected_date, "expected_date")

        def move() -> dict[str, Any]:
            source = _source_schedule(_calendar(source_date, source_date), schedule_id, expected_date)
            if source is None or not isinstance(source.get("workout_id"), int):
                return _conflict("source_schedule_changed")
            if source_date == destination:
                return _result("no_op", [{"action": "move", "state": "no_op", "schedule_id": schedule_id}], complete=True)
            workout_id = source["workout_id"]
            destination_rows = _calendar(destination, destination)
            if any(row.get("workout_id") not in {None, workout_id} for row in destination_rows):
                return _conflict("destination_occupied")
            existing = next((row for row in destination_rows if row.get("workout_id") == workout_id), None)
            if existing is not None:
                existing_schedule_id = existing.get("workout_schedule_id")
                if not isinstance(existing_schedule_id, int):
                    return _conflict("destination_schedule_id_unavailable")
                try:
                    unschedule_workout(schedule_id)
                except GarminCliError as exc:
                    return _result("partial", [{"action": "move", "state": "failed", "error_code": exc.error_code}])
                verified_op = {"action": "move", "state": "verified", "schedule_id": existing_schedule_id}
                return _result("complete", [verified_op], complete=True)
            try:
                raw = schedule_workout(workout_id, destination)
            except Exception as exc:
                if not _may_have_landed(exc):
                    raise
                return _result("unknown", [{"action": "schedule", "state": "unknown", "error_code": _error_code(exc)}])
            new_schedule_id = _extract_id(raw, "workoutScheduleId")
            reported_id = _landed_schedule(
                _calendar(destination, destination),
                new_schedule_id,
                workout_id,
                destination.isoformat(),
                _schedule_ids(destination_rows),
            )
            if reported_id is None:
                if new_schedule_id is None:
                    unavailable = [{"reason": "destination_schedule_id_unavailable"}]
                    return _result("unknown", [{"action": "schedule", "state": "unknown"}], conflicts=unavailable)
                try:
                    unschedule_workout(new_schedule_id)
                except GarminCliError:
                    return _result("unknown", [{"action": "schedule", "state": "unknown"}])
                return _result("compensated", [{"action": "schedule", "state": "compensated"}])
            moved_op = {"action": "move", "state": "verified", "schedule_id": reported_id}
            try:
                unschedule_workout(schedule_id)
            except GarminCliError as exc:
                failed_op = {"action": "unschedule", "schedule_id": schedule_id, "state": "failed", "error_code": exc.error_code}
                errors = [{"error_code": exc.error_code, "message": "Source unschedule did not complete."}]
                # The failed delete may still have removed the source remotely;
                # a complete re-read decides between success and compensation.
                try:
                    source_remains = _still_scheduled(schedule_id, source_date)
                except Exception:
                    return _result("unknown", [failed_op], errors=errors)
                if not source_remains:
                    # Desired end state reached: destination verified, source gone.
                    return _result("complete", [moved_op, failed_op], complete=True)
                if new_schedule_id is None:
                    # The verified destination row cannot be proven ours; leave it.
                    return _result("unknown", [failed_op], errors=errors)
                try:
                    unschedule_workout(new_schedule_id)
                except GarminCliError:
                    unknown_op = {"action": "schedule", "state": "unknown", "schedule_id": new_schedule_id}
                    return _result("unknown", [failed_op, unknown_op], errors=errors)
                compensated_op = {"action": "schedule", "state": "compensated", "schedule_id": new_schedule_id}
                return _result("compensated", [failed_op, compensated_op], errors=errors)
            return _result("complete", [moved_op], complete=True)

        return _authenticated(config, move)
