"""Strict plan validation and pure preview diffing for Garmin schedules."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from typing import Any

from garmin_cli.workout_schema import validate_workout_input

_PLAN_FIELDS = frozenset({"name", "description", "start_date", "end_date", "entries", "removals"})
_ENTRY_FIELDS = frozenset(
    {
        "entry_id",
        "date",
        "workout_id",
        "workout",
        "move_from_schedule_id",
        "replace_schedule_id",
        "expected_source_date",
    }
)
_REMOVAL_FIELDS = frozenset({"schedule_id", "expected_date"})
_WORKOUT_FIELDS = frozenset({"name", "description", "sport", "steps"})
_STEP_FIELDS = frozenset({"type", "duration", "target", "count", "steps"})
_DURATION_FIELDS = frozenset({"type", "value"})
_TARGET_FIELDS = frozenset({"type", "zone", "min", "max"})


def _is_positive_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _canonical_date(value: Any) -> date | None:
    """Parse only canonical YYYY-MM-DD strings.

    ``date.fromisoformat`` also accepts compact (20260715) and ISO-week forms;
    those would later fail the raw-string comparisons against Garmin calendar
    dates, so they are rejected here.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if value == parsed.isoformat() else None


def _unknown_fields(value: dict[str, Any], allowed: frozenset[str], path: str) -> list[str]:
    return [f"{path}: unknown field {key!r}" for key in sorted(set(value) - allowed)]


def _strict_workout_errors(workout: Any, path: str) -> list[str]:
    if not isinstance(workout, dict):
        return [f"{path}: workout must be an object"]
    errors = _unknown_fields(workout, _WORKOUT_FIELDS, path)
    errors.extend(f"{path}.{error}" for error in validate_workout_input(workout))
    steps = workout.get("steps")
    if not isinstance(steps, list):
        return errors
    for index, step in enumerate(steps):
        if isinstance(step, dict):
            errors.extend(_strict_step_unknown_errors(step, f"{path}.steps[{index}]"))
    return errors


def _strict_step_unknown_errors(step: dict[str, Any], path: str) -> list[str]:
    errors = _unknown_fields(step, _STEP_FIELDS, path)
    duration = step.get("duration")
    if isinstance(duration, dict):
        errors.extend(_unknown_fields(duration, _DURATION_FIELDS, f"{path}.duration"))
    target = step.get("target")
    if isinstance(target, dict):
        errors.extend(_unknown_fields(target, _TARGET_FIELDS, f"{path}.target"))
    nested = step.get("steps")
    if isinstance(nested, list):
        for index, child in enumerate(nested):
            if isinstance(child, dict):
                errors.extend(_strict_step_unknown_errors(child, f"{path}.steps[{index}]"))
    return errors


def validate_training_plan(plan: Any) -> list[str]:
    """Validate the closed v1 plan schema before any Garmin request."""
    if not isinstance(plan, dict):
        return ["plan must be an object"]
    errors = _unknown_fields(plan, _PLAN_FIELDS, "plan")
    name = plan.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 256:
        errors.append("plan.name must be a non-empty string of at most 256 characters")
    if "description" in plan and plan["description"] is not None and not isinstance(plan["description"], str):
        errors.append("plan.description must be a string when supplied")
    start = _canonical_date(plan.get("start_date"))
    end = _canonical_date(plan.get("end_date"))
    if start is None or end is None:
        errors.append("plan.start_date and plan.end_date must be YYYY-MM-DD")
    elif start > end:
        errors.append("plan.start_date must be on or before plan.end_date")
    elif (end - start).days + 1 > 90:
        errors.append("plan date range cannot exceed 90 days")
    entries = plan.get("entries")
    if not isinstance(entries, list):
        errors.append("plan.entries must be a list")
        entries = []
    if len(entries) > 50:
        errors.append("plan.entries cannot exceed 50")
    entry_ids: set[str] = set()
    source_schedule_ids: set[int] = set()
    entry_dates: Counter[str] = Counter()
    for index, entry in enumerate(entries):
        path = f"plan.entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{path} must be an object")
            continue
        errors.extend(_unknown_fields(entry, _ENTRY_FIELDS, path))
        entry_id = entry.get("entry_id")
        if not isinstance(entry_id, str) or not entry_id:
            errors.append(f"{path}.entry_id must be a non-empty string")
        elif entry_id in entry_ids:
            errors.append(f"{path}.entry_id must be unique")
        else:
            entry_ids.add(entry_id)
        entry_date = entry.get("date")
        parsed_date = _canonical_date(entry_date)
        if parsed_date is None:
            errors.append(f"{path}.date must be YYYY-MM-DD")
        elif start is not None and end is not None and not start <= parsed_date <= end:
            errors.append(f"{path}.date must be inside the plan date range")
        has_id = "workout_id" in entry
        has_inline = "workout" in entry
        if has_id == has_inline:
            errors.append(f"{path} must contain exactly one of workout_id or workout")
        if has_id and not _is_positive_id(entry.get("workout_id")):
            errors.append(f"{path}.workout_id must be a positive integer")
        if has_inline:
            errors.extend(_strict_workout_errors(entry.get("workout"), f"{path}.workout"))
        for key in ("move_from_schedule_id", "replace_schedule_id"):
            if key in entry and not _is_positive_id(entry[key]):
                errors.append(f"{path}.{key} must be a positive integer")
            elif key in entry:
                source_id = entry[key]
                if source_id in source_schedule_ids:
                    errors.append(f"{path}.{key} references a source schedule more than once")
                source_schedule_ids.add(source_id)
        if "move_from_schedule_id" in entry and "replace_schedule_id" in entry:
            errors.append(f"{path} cannot contain both move_from_schedule_id and replace_schedule_id")
        if ("move_from_schedule_id" in entry or "replace_schedule_id" in entry) and "expected_source_date" not in entry:
            errors.append(f"{path}.expected_source_date is required with a source schedule")
        if "expected_source_date" in entry and _canonical_date(entry["expected_source_date"]) is None:
            errors.append(f"{path}.expected_source_date must be YYYY-MM-DD")
        if isinstance(entry_date, str):
            # Apply rejects any occupied destination, so two entries on one
            # date would deterministically conflict with each other mid-apply.
            entry_dates[entry_date] += 1
    for entry_date_key, count in entry_dates.items():
        if count > 1:
            errors.append(f"multiple entries target the same date: {entry_date_key}")
    removals = plan.get("removals", [])
    if not isinstance(removals, list):
        errors.append("plan.removals must be a list")
    else:
        for index, removal in enumerate(removals):
            path = f"plan.removals[{index}]"
            if not isinstance(removal, dict):
                errors.append(f"{path} must be an object")
                continue
            errors.extend(_unknown_fields(removal, _REMOVAL_FIELDS, path))
            schedule_id = removal.get("schedule_id")
            if not _is_positive_id(schedule_id):
                errors.append(f"{path}.schedule_id must be a positive integer")
            elif not isinstance(schedule_id, int) or isinstance(schedule_id, bool):
                errors.append(f"{path}.schedule_id must be a positive integer")
            elif schedule_id in source_schedule_ids:
                errors.append(f"{path}.schedule_id references a source schedule more than once")
            else:
                source_schedule_ids.add(schedule_id)
            if _canonical_date(removal.get("expected_date")) is None:
                errors.append(f"{path}.expected_date must be YYYY-MM-DD")
    if isinstance(entries, list) and isinstance(removals, list) and not entries and not removals:
        errors.append("plan must contain at least one entry or removal")
    if start is not None and end is not None:
        calendar_dates = [start, end]
        for entry in entries:
            if isinstance(entry, dict) and (parsed := _canonical_date(entry.get("expected_source_date"))) is not None:
                calendar_dates.append(parsed)
        for removal in removals if isinstance(removals, list) else []:
            if isinstance(removal, dict) and (parsed := _canonical_date(removal.get("expected_date"))) is not None:
                calendar_dates.append(parsed)
        if (max(calendar_dates) - min(calendar_dates)).days + 1 > 90:
            errors.append("plan calendar read span cannot exceed 90 days")
    return errors


def _normalized_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _comparable_workout(value: Any) -> Any:
    """Normalize optional no-target and null-description fields for semantic comparisons."""
    if isinstance(value, list):
        return [_comparable_workout(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _comparable_workout(item)
        for key, item in value.items()
        if not (key == "target" and item == {"type": "no.target"}) and not (key == "description" and item is None)
    }


def _source_by_schedule(calendar: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in calendar:
        schedule_id = row.get("workout_schedule_id")
        if isinstance(schedule_id, int) and not isinstance(schedule_id, bool) and schedule_id > 0:
            result[schedule_id] = row
    return result


def preview_training_plan(
    plan: dict[str, Any],
    calendar: list[dict[str, Any]],
    workout_projections: dict[int, dict[str, Any] | None],
) -> dict[str, Any]:
    """Create a stable, read-only diff against current calendar state."""
    errors = validate_training_plan(plan)
    if errors:
        return {
            "complete": False,
            "operations": [],
            "errors": [{"error_code": "INVALID_INPUT", "message": error} for error in errors],
            "conflicts": [],
            "summary": {},
        }
    schedules = _source_by_schedule(calendar)
    operations: list[dict[str, Any]] = []
    conflicts: list[dict[str, str]] = []

    def projection_for(row: dict[str, Any]) -> dict[str, Any] | None:
        row_workout_id = row.get("workout_id")
        if not isinstance(row_workout_id, int) or isinstance(row_workout_id, bool):
            return None
        return workout_projections.get(row_workout_id)

    for entry in plan["entries"]:
        destination = entry["date"]
        same_date = [row for row in calendar if row.get("date") == destination]
        workout_id = entry.get("workout_id")
        inline = entry.get("workout")
        equivalent = next(
            (
                row
                for row in same_date
                if (workout_id is not None and row.get("workout_id") == workout_id)
                or (
                    inline is not None
                    and _normalized_json(_comparable_workout(projection_for(row)))
                    == _normalized_json(_comparable_workout(inline))
                )
            ),
            None,
        )
        source_id = entry.get("move_from_schedule_id") or entry.get("replace_schedule_id")
        source = schedules.get(source_id) if source_id is not None else None
        expected = entry.get("expected_source_date")
        # "absent" (id nowhere in the window) is how an already-applied move or
        # replacement looks on reapply; "changed" (present on another date)
        # means someone else moved it and is always a conflict.
        if source_id is None:
            source_state = "none"
        elif source is not None and (expected is None or source.get("date") == expected):
            source_state = "present"
        elif source is None:
            source_state = "absent"
        else:
            source_state = "changed"
        if equivalent is not None:
            operations.append(
                {
                    "entry_id": entry["entry_id"],
                    "action": "keep",
                    "state": "planned",
                    "date": destination,
                    "workout_id": equivalent.get("workout_id"),
                    "workout_schedule_id": equivalent.get("workout_schedule_id"),
                }
            )
            if source_state == "changed":
                conflicts.append({"entry_id": entry["entry_id"], "reason": "source_schedule_changed"})
            elif source_state == "present" and source is not None and source.get("workout_schedule_id") != equivalent.get("workout_schedule_id"):
                operations.append(
                    {
                        "action": "unschedule",
                        "state": "planned",
                        "source_schedule_id": source_id,
                        "date": source.get("date"),
                    }
                )
            continue
        if source_state in {"absent", "changed"}:
            conflicts.append({"entry_id": entry["entry_id"], "reason": "source_schedule_changed"})
            continue
        occupants = [
            row
            for row in same_date
            if row.get("workout_id") is not None and row.get("workout_schedule_id") != source_id
        ]
        if occupants:
            conflicts.append({"entry_id": entry["entry_id"], "reason": "destination_occupied"})
            continue
        if inline is not None:
            operations.append(
                {
                    "entry_id": entry["entry_id"],
                    "action": "create_template",
                    "state": "planned",
                    "date": destination,
                }
            )
        if entry.get("move_from_schedule_id"):
            action = "move"
        elif entry.get("replace_schedule_id"):
            action = "replace"
        else:
            action = "schedule"
        operations.append(
            {
                "entry_id": entry["entry_id"],
                "action": action,
                "state": "planned",
                "date": destination,
                "workout_id": workout_id,
                "source_schedule_id": source_id,
            }
        )
    for removal in plan.get("removals", []):
        source = schedules.get(removal["schedule_id"])
        if source is None:
            # Already gone: the desired end state, so reapply stays a no-op.
            operations.append(
                {
                    "action": "unschedule",
                    "state": "no_op",
                    "source_schedule_id": removal["schedule_id"],
                    "date": removal["expected_date"],
                }
            )
        elif source.get("date") != removal["expected_date"]:
            conflicts.append({"schedule_id": str(removal["schedule_id"]), "reason": "source_schedule_changed"})
        else:
            operations.append(
                {
                    "action": "unschedule",
                    "state": "planned",
                    "source_schedule_id": removal["schedule_id"],
                    "date": removal["expected_date"],
                }
            )
    scheduled = [op for op in operations if op["action"] in {"schedule", "move", "replace"}]
    return {
        "complete": not conflicts,
        "operations": operations,
        "errors": [],
        "conflicts": conflicts,
        "summary": {
            "scheduled_count": len(scheduled),
            "template_count": sum(op["action"] == "create_template" for op in operations),
        },
    }
