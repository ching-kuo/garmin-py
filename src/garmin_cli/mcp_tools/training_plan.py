"""Stateless preview and destructive application of structured training plans."""

from __future__ import annotations

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
from garmin_cli.exceptions import GarminCliError
from garmin_cli.mcp_tools._shared import _authenticated, _parse_date
from garmin_cli.serializers import serialize_calendar_workout, serialize_workout_detail
from garmin_cli.services.training_plan import preview_training_plan, validate_training_plan
from garmin_cli.workout_builder import build_garmin_payload


def _extract_id(raw: Any, key: str) -> int | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _calendar(start: date, end: date) -> list[dict[str, Any]]:
    return serialize_calendar_workout({"calendarItems": get_calendar_range(start, end)})


def _calendar_with_projections(start: date, end: date) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any] | None]]:
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


def _source_schedule(calendar: list[dict[str, Any]], schedule_id: int, expected_date: str) -> dict[str, Any] | None:
    return next(
        (row for row in calendar if row.get("workout_schedule_id") == schedule_id and row.get("date") == expected_date),
        None,
    )


def _compensate_new(new_schedules: list[int], new_templates: list[int], operations: list[dict[str, Any]]) -> bool:
    """Remove only resources created in this invocation, in reverse order."""
    successful = True
    for schedule_id in reversed(new_schedules):
        try:
            unschedule_workout(schedule_id)
            operations.append({"action": "unschedule", "schedule_id": schedule_id, "state": "compensated"})
        except GarminCliError:
            successful = False
            operations.append({"action": "unschedule", "schedule_id": schedule_id, "state": "unknown"})
    # A template may still be referenced by a schedule whose cleanup failed.
    # Keep all new templates in that case instead of risking a dangling entry.
    if not successful:
        return False
    for workout_id in reversed(new_templates):
        try:
            delete_workout(workout_id)
            operations.append({"action": "delete_template", "workout_id": workout_id, "state": "compensated"})
        except GarminCliError:
            successful = False
            operations.append({"action": "delete_template", "workout_id": workout_id, "state": "unknown"})
    return successful


def _restore_sources(removed_sources: list[dict[str, Any]], operations: list[dict[str, Any]]) -> bool:
    successful = True
    for source in reversed(removed_sources):
        workout_id, source_date = source.get("workout_id"), source.get("date")
        if not isinstance(workout_id, int) or not isinstance(source_date, str):
            successful = False
            continue
        try:
            schedule_workout(workout_id, date.fromisoformat(source_date))
            restored = any(
                row.get("workout_id") == workout_id
                for row in _calendar(date.fromisoformat(source_date), date.fromisoformat(source_date))
            )
            if not restored:
                successful = False
            operations.append(
                {
                    "action": "restore_source",
                    "workout_id": workout_id,
                    "date": source_date,
                    "state": "compensated" if restored else "unknown",
                }
            )
        except GarminCliError:
            successful = False
            operations.append(
                {
                    "action": "restore_source",
                    "workout_id": workout_id,
                    "date": source_date,
                    "state": "unknown",
                }
            )
    return successful


def _apply_plan(plan: dict[str, Any]) -> dict[str, Any]:
    start, end = _plan_dates(plan)
    calendar, projections = _calendar_with_projections(start, end)
    preview = preview_training_plan(plan, calendar, projections)
    if not preview["complete"]:
        return {**preview, "outcome": "partial"}
    operations: list[dict[str, Any]] = []
    new_schedules: list[int] = []
    new_templates: list[int] = []
    removed_sources: list[dict[str, Any]] = []
    source_removals: list[tuple[int, dict[str, Any]]] = []
    keep_by_entry = {
        operation["entry_id"]: operation
        for operation in preview["operations"]
        if operation.get("action") == "keep" and isinstance(operation.get("entry_id"), str)
    }
    entered_destructive_stage = False
    # Set when a write happened whose identifier is unknown: such a write can
    # never be compensated, so a later failure must report `unknown`.
    unidentified_write = False
    try:
        for entry in plan["entries"]:
            keep = keep_by_entry.get(entry["entry_id"])
            workout_id = keep.get("workout_id") if keep is not None else entry.get("workout_id")
            destination_schedule_id = keep.get("workout_schedule_id") if keep is not None else None
            if keep is not None:
                operations.append({**keep, "state": "no_op"})
            elif "workout" in entry:
                raw = create_workout(build_garmin_payload(entry["workout"]))
                workout_id = _extract_id(raw, "workoutId")
                if workout_id is None:
                    unidentified_write = True
                    operations.append({"entry_id": entry["entry_id"], "action": "create_template", "state": "unknown"})
                    raise GarminCliError("Workout creation returned no identifier.", "SERVER_ERROR")
                new_templates.append(workout_id)
                operations.append(
                    {
                        "entry_id": entry["entry_id"],
                        "action": "create_template",
                        "workout_id": workout_id,
                        "state": "applied",
                    }
                )
            if not isinstance(workout_id, int):
                raise GarminCliError("Workout identifier is unavailable.", "INTERNAL_ERROR")
            if keep is None:
                destination = date.fromisoformat(entry["date"])
                destination_rows = _calendar(destination, destination)
                existing = next((row for row in destination_rows if row.get("workout_id") == workout_id), None)
                if existing is not None:
                    destination_schedule_id = existing.get("workout_schedule_id")
                    operations.append(
                        {
                            "entry_id": entry["entry_id"],
                            "action": "schedule",
                            "date": entry["date"],
                            "workout_id": workout_id,
                            "state": "no_op",
                            "workout_schedule_id": destination_schedule_id,
                        }
                    )
                else:
                    entry_source_id = entry.get("move_from_schedule_id") or entry.get("replace_schedule_id")
                    # An occupied destination is tolerated only when every
                    # occupant is the entry's own source (same-date replace);
                    # a move/replace flag must not unlock unrelated occupants.
                    blocking = [
                        row
                        for row in destination_rows
                        if row.get("workout_id") is not None and row.get("workout_schedule_id") != entry_source_id
                    ]
                    if blocking:
                        raise GarminCliError("Destination date has a scheduled workout.", "INVALID_INPUT")
                    raw_schedule = schedule_workout(workout_id, destination)
                    schedule_id = _extract_id(raw_schedule, "workoutScheduleId")
                    if schedule_id is not None:
                        new_schedules.append(schedule_id)
                    else:
                        unidentified_write = True
                    verified_rows = _calendar(destination, destination)
                    verified = next((row for row in verified_rows if row.get("workout_id") == workout_id), None)
                    if verified is None:
                        raise GarminCliError("New schedule could not be verified.", "SERVER_ERROR")
                    verified_id = verified.get("workout_schedule_id")
                    # Compensation may only touch the id our own write returned;
                    # a differing verified id can belong to a concurrent actor.
                    if schedule_id is not None:
                        destination_schedule_id = schedule_id
                    elif isinstance(verified_id, int):
                        destination_schedule_id = verified_id
                    else:
                        raise GarminCliError("New schedule identifier is unavailable.", "SERVER_ERROR")
                    operations.append(
                        {
                            "entry_id": entry["entry_id"],
                            "action": "schedule",
                            "date": entry["date"],
                            "workout_id": workout_id,
                            "workout_schedule_id": destination_schedule_id,
                            "state": "verified",
                        }
                    )
            source_id = entry.get("move_from_schedule_id") or entry.get("replace_schedule_id")
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
        entered_destructive_stage = True
        for schedule_id, source in source_removals:
            unschedule_workout(schedule_id)
            removed_sources.append(source)
            operations.append({"action": "unschedule", "schedule_id": schedule_id, "state": "applied"})
        performed_write = any(operation.get("state") in {"applied", "verified"} for operation in operations)
        outcome = "complete" if performed_write else "no_op"
        return {"complete": True, "outcome": outcome, "operations": operations, "errors": [], "conflicts": []}
    except Exception as exc:
        # Any failure mid-apply (including non-Garmin bugs) must attempt
        # compensation; leaving half a destructive plan applied is worse than
        # reporting an internal error with a restored calendar.
        error_code = exc.error_code if isinstance(exc, GarminCliError) else "INTERNAL_ERROR"
        # A failed unschedule with a transport-ambiguous code may still have
        # removed the schedule remotely, so the end state cannot be trusted.
        ambiguous_destructive = entered_destructive_stage and error_code not in {"INVALID_INPUT", "NOT_FOUND"}
        if entered_destructive_stage:
            restored = _restore_sources(removed_sources, operations)
            cleaned = _compensate_new(new_schedules, new_templates, operations)
            fully_known = restored and cleaned and not ambiguous_destructive
        else:
            fully_known = _compensate_new(new_schedules, new_templates, operations)
        outcome = "compensated" if fully_known and not unidentified_write else "unknown"
        operations.append({"action": "apply", "state": "failed", "error_code": error_code})
        return {
            "complete": False,
            "outcome": outcome,
            "operations": operations,
            "errors": [{"error_code": error_code, "message": "Plan application did not complete."}],
            "conflicts": [],
        }


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
        """
        if not isinstance(schedule_id, int) or isinstance(schedule_id, bool) or schedule_id <= 0:
            raise ToolError("schedule_id must be a positive integer")
        destination = _parse_date(new_date, "new_date")
        source_date = _parse_date(expected_date, "expected_date")

        def move() -> dict[str, Any]:
            source_rows = _calendar(source_date, source_date)
            source = _source_schedule(source_rows, schedule_id, expected_date)
            if source is None or not isinstance(source.get("workout_id"), int):
                return {
                    "complete": False,
                    "outcome": "partial",
                    "operations": [],
                    "errors": [],
                    "conflicts": [{"reason": "source_schedule_changed"}],
                }
            if source_date == destination:
                return {
                    "complete": True,
                    "outcome": "no_op",
                    "operations": [{"action": "move", "state": "no_op", "schedule_id": schedule_id}],
                    "errors": [],
                    "conflicts": [],
                }
            destination_rows = _calendar(destination, destination)
            existing = next(
                (row for row in destination_rows if row.get("workout_id") == source["workout_id"]),
                None,
            )
            if existing is not None:
                existing_schedule_id = existing.get("workout_schedule_id")
                if not isinstance(existing_schedule_id, int):
                    return {
                        "complete": False,
                        "outcome": "partial",
                        "operations": [],
                        "errors": [],
                        "conflicts": [{"reason": "destination_schedule_id_unavailable"}],
                    }
                try:
                    unschedule_workout(schedule_id)
                except GarminCliError as exc:
                    return {
                        "complete": False,
                        "outcome": "partial",
                        "operations": [{"action": "move", "state": "failed", "error_code": exc.error_code}],
                        "errors": [],
                        "conflicts": [],
                    }
                return {
                    "complete": True,
                    "outcome": "complete",
                    "operations": [{"action": "move", "state": "verified", "schedule_id": existing_schedule_id}],
                    "errors": [],
                    "conflicts": [],
                }
            raw = schedule_workout(source["workout_id"], destination)
            new_schedule_id = _extract_id(raw, "workoutScheduleId")
            verified = next(
                (row for row in _calendar(destination, destination) if row.get("workout_id") == source["workout_id"]), None
            )
            if verified is None:
                if new_schedule_id is None:
                    return {
                        "complete": False,
                        "outcome": "unknown",
                        "operations": [{"action": "schedule", "state": "unknown"}],
                        "errors": [],
                        "conflicts": [],
                    }
                try:
                    unschedule_workout(new_schedule_id)
                except GarminCliError:
                    return {
                        "complete": False,
                        "outcome": "unknown",
                        "operations": [{"action": "schedule", "state": "unknown"}],
                        "errors": [],
                        "conflicts": [],
                    }
                return {
                    "complete": False,
                    "outcome": "compensated",
                    "operations": [{"action": "schedule", "state": "compensated"}],
                    "errors": [],
                    "conflicts": [],
                }
            # Trust only the id our own write returned; a differing verified id
            # may belong to a concurrent schedule and must never be deleted.
            verified_schedule_id = verified.get("workout_schedule_id")
            reported_id = new_schedule_id if new_schedule_id is not None else (
                verified_schedule_id if isinstance(verified_schedule_id, int) else None
            )
            if reported_id is None:
                return {
                    "complete": False,
                    "outcome": "unknown",
                    "operations": [{"action": "schedule", "state": "unknown"}],
                    "errors": [],
                    "conflicts": [{"reason": "destination_schedule_id_unavailable"}],
                }
            try:
                unschedule_workout(schedule_id)
            except GarminCliError as exc:
                failed_op = {
                    "action": "unschedule",
                    "schedule_id": schedule_id,
                    "state": "failed",
                    "error_code": exc.error_code,
                }
                error_entry = {"error_code": exc.error_code, "message": "Source unschedule did not complete."}
                # The failed delete may still have removed the source remotely;
                # re-read before deciding between success and compensation.
                try:
                    source_remains = any(
                        row.get("workout_schedule_id") == schedule_id for row in _calendar(source_date, source_date)
                    )
                except GarminCliError:
                    return {"complete": False, "outcome": "unknown", "operations": [failed_op], "errors": [error_entry], "conflicts": []}
                if not source_remains:
                    # Desired end state reached: destination verified, source gone.
                    return {
                        "complete": True,
                        "outcome": "complete",
                        "operations": [{"action": "move", "state": "verified", "schedule_id": reported_id}, failed_op],
                        "errors": [],
                        "conflicts": [],
                    }
                if new_schedule_id is None:
                    # The verified destination row cannot be proven ours; leave it.
                    return {"complete": False, "outcome": "unknown", "operations": [failed_op], "errors": [error_entry], "conflicts": []}
                try:
                    unschedule_workout(new_schedule_id)
                except GarminCliError:
                    return {
                        "complete": False,
                        "outcome": "unknown",
                        "operations": [failed_op, {"action": "schedule", "state": "unknown", "schedule_id": new_schedule_id}],
                        "errors": [error_entry],
                        "conflicts": [],
                    }
                return {
                    "complete": False,
                    "outcome": "compensated",
                    "operations": [failed_op, {"action": "schedule", "state": "compensated", "schedule_id": new_schedule_id}],
                    "errors": [error_entry],
                    "conflicts": [],
                }
            return {
                "complete": True,
                "outcome": "complete",
                "operations": [{"action": "move", "state": "verified", "schedule_id": reported_id}],
                "errors": [],
                "conflicts": [],
            }

        return _authenticated(config, move)
