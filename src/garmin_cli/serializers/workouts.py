"""Serializers for workout-domain Garmin Connect payloads.

Covers the workout list/get/detail surface, scheduled-calendar workouts, and
create/update mutation responses, plus their COLUMNS_* constants.
"""
from __future__ import annotations

from typing import Any

from garmin_cli.serializers._common import (
    _coalesce,
    _get_nested,
    _listify,
    _minutes,
)

COLUMNS_CALENDAR_WORKOUT = ("date", "id", "name", "type", "duration_min", "description")
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


def serialize_calendar_workout(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("calendarItems", []) if isinstance(raw, dict) else []
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "date": item.get("date"),
                "id": _coalesce(item.get("workoutId"), item.get("id")),
                "name": item.get("title"),
                "type": item.get("workoutTypeKey"),
                "duration_min": _minutes(item.get("durationInSeconds")),
                "description": item.get("note"),
            }
        )
    return rows


def serialize_workout_summary(raw: Any) -> list[dict[str, Any]]:
    return [_normalize_workout_base(item) for item in _listify(raw)]


def serialize_workout_detail(raw: Any) -> list[dict[str, Any]]:
    workout = raw if isinstance(raw, dict) else {}
    row = _normalize_workout_base(workout)
    steps: list[dict[str, Any]] = []
    for segment in workout.get("workoutSegments", []):
        if not isinstance(segment, dict):
            continue
        for step in segment.get("workoutSteps", []):
            if not isinstance(step, dict):
                continue
            steps.append(
                {
                    "step_order": _coalesce(step.get("stepOrder"), step.get("order")),
                    "step_type": _coalesce(
                        _get_nested(step, "stepType", "stepTypeKey"),
                        step.get("stepTypeKey"),
                        step.get("type"),
                    ),
                    "duration_type": step.get("durationType"),
                    "duration_value": step.get("durationValue"),
                    "target_type": _coalesce(
                        step.get("targetType"),
                        _get_nested(step, "target", "targetType"),
                    ),
                    "target_value_low": _coalesce(step.get("targetValueOne"), step.get("targetValueLow")),
                    "target_value_high": _coalesce(step.get("targetValueTwo"), step.get("targetValueHigh")),
                }
            )
    row["steps"] = steps
    row["steps_summary"] = " > ".join(
        step_type for step in steps if (step_type := step.get("step_type"))
    )
    return [row]


def serialize_workout_mutate(raw: Any, status: str) -> list[dict[str, Any]]:
    """Serialize a create/update response with a status field."""
    row = _normalize_workout_base(raw if isinstance(raw, dict) else {})
    return [{**row, "status": status}]
