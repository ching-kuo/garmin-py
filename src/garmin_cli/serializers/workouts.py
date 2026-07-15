"""Serializers for workout-domain Garmin Connect payloads.

Covers the workout list/get/detail surface, scheduled-calendar workouts, and
create/update mutation responses, plus their COLUMNS_* constants.
"""
from __future__ import annotations

import copy
from typing import Any

from garmin_cli.metrics import FieldEntry, FieldTable, validate_table_coverage
from garmin_cli.serializers._common import (
    _coalesce,
    _get_nested,
    _listify,
    _minutes,
)
from garmin_cli.workout_schema import (
    RANGE_TARGETS,
    SPORT_TYPES,
    STEP_TYPES,
    TARGET_TYPES,
    ZONE_TARGETS,
    validate_workout_input,
)

COLUMNS_CALENDAR_WORKOUT = (
    "date",
    "id",
    "workout_id",
    "workout_schedule_id",
    "name",
    "type",
    "duration_min",
    "description",
    "item_type",
    "is_race",
    "primary_event",
    "event_time",
    "location",
)
COLUMNS_WORKOUT = ("id", "name", "sport", "duration_min", "description")
COLUMNS_WORKOUT_DETAIL = (
    "id",
    "name",
    "sport",
    "duration_min",
    "description",
    "steps_summary",
)
COLUMNS_WORKOUT_MUTATE = ("id", "name", "sport", "duration_min", "status")


def _normalize_workout_base(workout: dict[str, Any]) -> dict[str, Any]:
    duration_seconds = _coalesce(
        workout.get("estimatedDurationInSecs"),
        workout.get("estimatedDuration"),
        workout.get("duration"),
    )
    raw_sport_type = workout.get("sportType")
    sport_type = raw_sport_type if isinstance(raw_sport_type, dict) else {}
    return {
        "id": _coalesce(workout.get("workoutId"), workout.get("id")),
        "name": _coalesce(workout.get("workoutName"), workout.get("name")),
        "sport": _coalesce(
            sport_type.get("sportTypeKey"),
            sport_type.get("displayName"),
            sport_type.get("key"),
            workout.get("sport"),
            workout.get("type"),
        ),
        "duration_min": _minutes(duration_seconds),
        "description": workout.get("description"),
    }


# Calendar items are a union of scheduled workouts, races/events, and logged
# entries; itemType + the race/event flags let coaching consumers find target
# races on the calendar.
_CALENDAR_WORKOUT_TABLE = FieldTable(
    name="calendar_workout",
    columns=COLUMNS_CALENDAR_WORKOUT,
    entries=(
        FieldEntry("date", (("date",),)),
        FieldEntry("id", (("workoutId",), ("id",))),
        FieldEntry("workout_id", (("workoutId",),)),
        FieldEntry("workout_schedule_id", (("workoutScheduleId",),)),
        FieldEntry("name", (("title",),)),
        FieldEntry("type", (("workoutTypeKey",),)),
        FieldEntry("duration_min", (("durationInSeconds",),), _minutes),
        FieldEntry("description", (("note",),)),
        FieldEntry("item_type", (("itemType",),)),
        FieldEntry("is_race", (("isRace",),)),
        FieldEntry("primary_event", (("primaryEvent",),)),
        FieldEntry("event_time", (("eventTimeLocal",),)),
        FieldEntry("location", (("location",),)),
    ),
)


def serialize_calendar_workout(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("calendarItems", []) if isinstance(raw, dict) else []
    return _CALENDAR_WORKOUT_TABLE.project_all(
        [item for item in items if isinstance(item, dict)]
    )


def serialize_workout_summary(raw: Any) -> list[dict[str, Any]]:
    return [_normalize_workout_base(item) for item in _listify(raw)]


def _step_type_key(step: dict[str, Any]) -> Any:
    step_type = _coalesce(
        _get_nested(step, "stepType", "stepTypeKey"),
        step.get("stepTypeKey"),
        step.get("type"),
    )
    return "repeat" if step_type == "RepeatGroupDTO" else step_type


def _target_type_key(step: dict[str, Any]) -> Any:
    target_type = step.get("targetType")
    if isinstance(target_type, dict):
        return _coalesce(
            target_type.get("workoutTargetTypeKey"),
            target_type.get("targetTypeKey"),
        )
    return _coalesce(target_type, _get_nested(step, "target", "targetType"))


def _normalize_target(step: dict[str, Any]) -> dict[str, Any] | None:
    target_type = _target_type_key(step)
    if target_type is None:
        return None
    target_type = "speed.zone" if target_type == "pace.zone" else target_type
    target: dict[str, Any] = {"type": target_type}
    if target_type in ZONE_TARGETS:
        target["zone"] = _coalesce(step.get("zoneNumber"), step.get("targetValueOne"))
    elif target_type in RANGE_TARGETS:
        target["min"] = _coalesce(step.get("targetValueOne"), step.get("targetValueLow"))
        target["max"] = _coalesce(step.get("targetValueTwo"), step.get("targetValueHigh"))
    return target


def _normalize_workout_step(step: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Garmin step while retaining every original field.

    Garmin represents repeat groups as a step with nested ``workoutSteps``;
    preserving that tree prevents an update client from mistaking a repeat for
    a flat sequence. ``raw`` is intentionally retained because Garmin adds
    step variants faster than the simplified write schema can support them.
    """
    end_condition = step.get("endCondition")
    if not isinstance(end_condition, dict):
        end_condition = {}
    duration_type = _coalesce(
        step.get("durationType"),
        end_condition.get("conditionTypeKey"),
    )
    duration_value = _coalesce(step.get("durationValue"), step.get("endConditionValue"))
    nested = step.get("workoutSteps")
    nested_steps = [
        _normalize_workout_step(child)
        for child in nested
        if isinstance(child, dict)
    ] if isinstance(nested, list) else []
    target = _normalize_target(step)
    step_type = _step_type_key(step)
    result: dict[str, Any] = {
        "step_order": _coalesce(step.get("stepOrder"), step.get("order")),
        "step_type": step_type,
        "duration": {"type": duration_type, "value": duration_value},
        "target": target,
        "repeat_count": duration_value if step_type == "repeat" else None,
        "steps": nested_steps,
        "raw": copy.deepcopy(step),
        # Compatibility keys retained for consumers of the original flattened
        # projection.
        "duration_type": duration_type,
        "duration_value": duration_value,
        "target_type": target.get("type") if target else None,
        "target_value_low": target.get("min") if target else None,
        "target_value_high": target.get("max") if target else None,
    }
    return result


def _workout_step_to_write_input(
    step: dict[str, Any], path: str, reasons: list[dict[str, str]], repeat_depth: int = 0
) -> dict[str, Any] | None:
    step_type = step.get("step_type")
    if step_type not in STEP_TYPES:
        reasons.append({"path": path, "reason": "unsupported_step_type"})
        return None
    if step_type == "repeat":
        if repeat_depth:
            reasons.append({"path": path, "reason": "nested_repeat"})
            return None
        count = step.get("repeat_count")
        if not isinstance(count, int) or isinstance(count, bool):
            reasons.append({"path": path, "reason": "invalid_repeat_count"})
            return None
        nested = step.get("steps")
        if not isinstance(nested, list) or not nested:
            reasons.append({"path": path, "reason": "repeat_missing_steps"})
            return None
        children = [
            _workout_step_to_write_input(child, f"{path}.steps[{index}]", reasons, repeat_depth + 1)
            for index, child in enumerate(nested)
        ]
        if any(child is None for child in children):
            return None
        return {"type": "repeat", "count": count, "steps": children}

    duration = step.get("duration")
    if not isinstance(duration, dict) or duration.get("type") not in {"time", "distance"}:
        reasons.append({"path": f"{path}.duration", "reason": "unsupported_duration"})
        return None
    value = duration.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        reasons.append({"path": f"{path}.duration.value", "reason": "invalid_duration"})
        return None

    result: dict[str, Any] = {
        "type": step_type,
        "duration": {"type": duration["type"], "value": value},
    }
    target = step.get("target")
    if target is not None:
        if not isinstance(target, dict) or target.get("type") not in TARGET_TYPES:
            reasons.append({"path": f"{path}.target", "reason": "unsupported_target"})
            return None
        target_type = target["type"]
        simplified_target: dict[str, Any] = {"type": target_type}
        if target_type in ZONE_TARGETS:
            if not isinstance(target.get("zone"), int) or isinstance(target.get("zone"), bool):
                reasons.append({"path": f"{path}.target.zone", "reason": "missing_zone"})
                return None
            simplified_target["zone"] = target["zone"]
        if target_type in RANGE_TARGETS:
            if target.get("min") is None or target.get("max") is None:
                reasons.append({"path": f"{path}.target", "reason": "missing_target_bounds"})
                return None
            simplified_target["min"] = target["min"]
            simplified_target["max"] = target["max"]
        result["target"] = simplified_target
    return result


def _write_projection(
    workout: dict[str, Any], row: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    reasons: list[dict[str, str]] = []
    segments = row["segments"]
    if len(segments) != 1:
        reasons.append({"path": "segments", "reason": "multiple_segments"})
        return None, reasons
    if row.get("sport") not in SPORT_TYPES:
        reasons.append({"path": "sport", "reason": "unsupported_sport"})
    normalized_steps = segments[0]["steps"]
    steps = [
        _workout_step_to_write_input(step, f"segments[0].steps[{index}]", reasons)
        for index, step in enumerate(normalized_steps)
    ]
    if reasons or any(step is None for step in steps):
        return None, reasons
    projection: dict[str, Any] = {
        "name": row.get("name"),
        "sport": row.get("sport"),
        "steps": steps,
    }
    if workout.get("description") is not None:
        projection["description"] = workout["description"]
    validation_errors = validate_workout_input(projection)
    if validation_errors:
        reasons.extend(
            {"path": "write_projection", "reason": error}
            for error in validation_errors
        )
        return None, reasons
    return projection, reasons


def _legacy_flat_step(step: dict[str, Any]) -> dict[str, Any]:
    """Project the pre-Release-A flat step shape for compatibility."""
    raw = step.get("raw")
    raw_step = raw if isinstance(raw, dict) else {}
    return {
        "step_order": step.get("step_order"),
        "step_type": step.get("step_type"),
        "duration_type": step.get("duration_type"),
        "duration_value": step.get("duration_value"),
        "target_type": step.get("target_type"),
        "target_value_low": _coalesce(
            raw_step.get("targetValueOne"), raw_step.get("targetValueLow")
        ),
        "target_value_high": _coalesce(
            raw_step.get("targetValueTwo"), raw_step.get("targetValueHigh")
        ),
    }


def serialize_workout_detail(raw: Any) -> list[dict[str, Any]]:
    workout = raw if isinstance(raw, dict) else {}
    row = _normalize_workout_base(workout)
    segments: list[dict[str, Any]] = []
    raw_segments = workout.get("workoutSegments")
    for segment_index, segment in enumerate(raw_segments if isinstance(raw_segments, list) else []):
        if not isinstance(segment, dict):
            continue
        sport_type = segment.get("sportType")
        segment_sport = sport_type.get("sportTypeKey") if isinstance(sport_type, dict) else None
        raw_steps = segment.get("workoutSteps")
        normalized_steps = [
            _normalize_workout_step(step)
            for step in raw_steps
            if isinstance(step, dict)
        ] if isinstance(raw_steps, list) else []
        segments.append({
            "segment_order": _coalesce(segment.get("segmentOrder"), segment_index + 1),
            "sport": segment_sport,
            "steps": normalized_steps,
            "raw": copy.deepcopy(segment),
        })
    row["segments"] = segments
    # Preserve the previous flat compatibility view. New callers should use
    # ``segments`` because flattening cannot represent repeats or multisport
    # workouts without loss.
    structured_steps = [step for segment in segments for step in segment["steps"]]
    row["steps"] = [_legacy_flat_step(step) for step in structured_steps]
    row["steps_summary"] = " > ".join(
        step_type for step in structured_steps if (step_type := step.get("step_type"))
    )
    projection, reasons = _write_projection(workout, row)
    row["write_compatible"] = projection is not None
    row["write_projection"] = projection
    row["write_incompatibilities"] = reasons
    return [row]


def serialize_workout_mutate(raw: Any, status: str) -> list[dict[str, Any]]:
    """Serialize a create/update response with a status field."""
    row = _normalize_workout_base(raw if isinstance(raw, dict) else {})
    return [{**row, "status": status}]


# Import-time guard: the calendar serializer is table-backed; the workout
# summary/detail/mutate serializers stay bespoke (shared _normalize_workout_base
# plus structural step flattening) and are exempt.
validate_table_coverage(
    "workouts",
    {
        "COLUMNS_CALENDAR_WORKOUT": COLUMNS_CALENDAR_WORKOUT,
        "COLUMNS_WORKOUT": COLUMNS_WORKOUT,
        "COLUMNS_WORKOUT_DETAIL": COLUMNS_WORKOUT_DETAIL,
        "COLUMNS_WORKOUT_MUTATE": COLUMNS_WORKOUT_MUTATE,
    },
    (_CALENDAR_WORKOUT_TABLE,),
    exempt=frozenset(
        {"COLUMNS_WORKOUT", "COLUMNS_WORKOUT_DETAIL", "COLUMNS_WORKOUT_MUTATE"}
    ),
)
