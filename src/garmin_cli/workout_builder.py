"""Transform simplified LLM-friendly workout schema to Garmin API format."""
from __future__ import annotations

import copy

from garmin_cli.exceptions import GarminCliError
from garmin_cli.workout_schema import (
    CUSTOM_RANGE_WIRE_TYPES,
    END_CONDITIONS,
    RANGE_TARGETS,
    READ_ONLY_FIELDS,
    SPORT_TYPES,
    STEP_TYPES,
    TARGET_TYPES,
    ZONE_TARGETS,
    is_custom_range,
    is_positive_id,
)


def _estimate_step_metrics(step: dict) -> tuple[int, int]:
    """Return estimated (duration_secs, distance_meters) for one simplified step."""
    if step["type"] == "repeat":
        count = step.get("count", 0)
        nested_duration = 0
        nested_distance = 0
        for nested in step.get("steps", []):
            duration_secs, distance_meters = _estimate_step_metrics(nested)
            nested_duration += duration_secs
            nested_distance += distance_meters
        return nested_duration * count, nested_distance * count

    duration = step["duration"]
    duration_type = duration["type"]
    duration_value = duration["value"]
    if duration_type == "time":
        return duration_value, 0
    if duration_type == "distance":
        return 0, duration_value
    return 0, 0


def _compute_estimated_metrics(steps: list[dict]) -> dict:
    """Return aggregate estimated metadata derived from simplified steps."""
    duration_secs = 0
    distance_meters = 0
    for step in steps:
        step_duration, step_distance = _estimate_step_metrics(step)
        duration_secs += step_duration
        distance_meters += step_distance

    metrics: dict = {}
    if duration_secs > 0:
        metrics["estimatedDurationInSecs"] = duration_secs
    if distance_meters > 0:
        metrics["estimatedDistanceInMeters"] = distance_meters
    return metrics


def _build_target(target: dict | None) -> tuple[dict, dict]:
    """Build (targetType_dict, extra_fields_dict) from a target spec.

    Returns a tuple of:
        - targetType dict (workoutTargetTypeId, workoutTargetTypeKey)
        - extra fields to merge into the step (e.g. zoneNumber, targetValueOne/Two)
    """
    target = target or {}
    target_type_key = target.get("type", "no.target")
    custom_range = is_custom_range(target)
    wire = CUSTOM_RANGE_WIRE_TYPES.get(target_type_key) if custom_range else None
    api_key, type_id = wire or TARGET_TYPES.get(target_type_key, (target_type_key, 1))
    target_type = {"workoutTargetTypeId": type_id, "workoutTargetTypeKey": api_key}

    if target_type_key in RANGE_TARGETS or custom_range:
        # A custom bpm/watt range sends zoneNumber null (live shape).
        extra: dict = {"zoneNumber": None} if custom_range else {}
        if "min" in target:
            extra["targetValueOne"] = target["min"]
        if "max" in target:
            extra["targetValueTwo"] = target["max"]
        return target_type, extra

    if target_type_key in ZONE_TARGETS:
        extra = {}
        if "zone" in target:
            extra["zoneNumber"] = target["zone"]
        return target_type, extra

    # Generic (no.target, open, etc.)
    return target_type, {}


def _build_step(step: dict, order: int) -> dict:
    """Build a single Garmin step dict from a simplified step dict."""
    step_type_key = step["type"]

    if step_type_key == "repeat":
        nested_steps = [
            _build_step(nested, i + 1) for i, nested in enumerate(step.get("steps", []))
        ]
        return {
            "type": "RepeatGroupDTO",
            "stepOrder": order,
            "endCondition": {
                "conditionTypeId": END_CONDITIONS["iterations"],
                "conditionTypeKey": "iterations",
            },
            "endConditionValue": step["count"],
            "workoutSteps": nested_steps,
        }

    step_type_id = STEP_TYPES.get(step_type_key)
    if step_type_id is None:
        raise GarminCliError(
            error=f"Unknown step type: {step_type_key!r}", error_code="INVALID_INPUT"
        )
    duration = step["duration"]
    dur_type_key = duration["type"]
    dur_type_id = END_CONDITIONS.get(dur_type_key)
    if dur_type_id is None:
        raise GarminCliError(
            error=f"Unknown duration type: {dur_type_key!r}", error_code="INVALID_INPUT"
        )
    dur_value = duration["value"]

    target_type, extra = _build_target(step.get("target"))

    result: dict = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {
            "stepTypeId": step_type_id,
            "stepTypeKey": step_type_key,
        },
        "endCondition": {
            "conditionTypeId": dur_type_id,
            "conditionTypeKey": dur_type_key,
        },
        "endConditionValue": dur_value,
        "targetType": target_type,
    }
    result.update(extra)
    return result


def _build_sport_type(sport_key: str) -> dict:
    sport_id = SPORT_TYPES.get(sport_key)
    if sport_id is None:
        raise GarminCliError(
            error=f"Unknown sport type: {sport_key!r}", error_code="INVALID_INPUT"
        )
    return {
        "sportTypeId": sport_id,
        "sportTypeKey": sport_key,
    }


def _build_segments(steps: list[dict], sport_type: dict) -> list[dict]:
    """Build workoutSegments list from simplified steps and a sport_type dict."""
    workout_steps = [
        _build_step(step, i + 1) for i, step in enumerate(steps)
    ]
    return [
        {
            "segmentOrder": 1,
            "sportType": dict(sport_type),
            "workoutSteps": workout_steps,
        }
    ]


def build_garmin_payload(input_data: dict) -> dict:
    """Transform simplified workout input to Garmin API payload.

    Does not mutate input_data.

    Args:
        input_data: Simplified workout dict with keys: name, sport, steps,
                    and optionally description.

    Returns:
        Garmin API format dict.
    """
    sport_key = input_data["sport"]
    sport_type = _build_sport_type(sport_key)

    payload: dict = {
        "workoutName": input_data["name"],
        "sportType": sport_type,
        "workoutSegments": _build_segments(input_data["steps"], sport_type),
    }

    if "description" in input_data:
        payload["description"] = input_data["description"]

    payload.update(_compute_estimated_metrics(input_data["steps"]))

    return payload


def merge_workout_payload(existing: dict, user_input: dict) -> tuple[dict, list[str]]:
    """Merge user changes into an existing Garmin workout payload.

    Does not mutate either input.

    Args:
        existing: Current Garmin API workout dict.
        user_input: Simplified user-supplied changes (same schema as build_garmin_payload input).

    Returns:
        Tuple of (merged_dict, warnings_list).
        warnings_list contains one entry per read-only field that user_input tried to set.
    """
    merged = copy.deepcopy(existing)
    warnings: list[str] = []

    # Detect and warn about read-only fields in user_input
    for field in READ_ONLY_FIELDS:
        if field in user_input:
            warnings.append(
                f"Field '{field}' is read-only and cannot be modified; existing value preserved."
            )

    # Apply user changes (mapped to Garmin API field names)
    if "name" in user_input:
        merged["workoutName"] = user_input["name"]

    if "sport" in user_input:
        sport_type = _build_sport_type(user_input["sport"])
        merged["sportType"] = sport_type
        segments = merged.get("workoutSegments", [])
        if isinstance(segments, list) and len(segments) == 1:
            segment = segments[0]
            if isinstance(segment, dict):
                segment["sportType"] = dict(sport_type)

    if "description" in user_input:
        merged["description"] = user_input["description"]

    if "steps" in user_input:
        # Reuse the stored sport as-is: Garmin sub-sports (trail_running,
        # road_biking, ...) are outside SPORT_TYPES but valid to keep.
        stored = merged.get("sportType")
        stored_sport = dict(stored) if isinstance(stored, dict) else {}
        sport_key = stored_sport.get("sportTypeKey")
        if isinstance(sport_key, str) and sport_key in SPORT_TYPES and not is_positive_id(stored_sport.get("sportTypeId")):
            stored_sport["sportTypeId"] = SPORT_TYPES[sport_key]
        if not (isinstance(sport_key, str) and sport_key and is_positive_id(stored_sport.get("sportTypeId"))):
            raise GarminCliError(
                error="Existing workout has no usable sportType; include 'sport' with the new steps.",
                error_code="INVALID_INPUT",
            )
        merged["sportType"] = stored_sport
        merged["workoutSegments"] = _build_segments(user_input["steps"], stored_sport)
        metrics = _compute_estimated_metrics(user_input["steps"])
        for key in ("estimatedDurationInSecs", "estimatedDistanceInMeters"):
            if key in metrics:
                merged[key] = metrics[key]
            else:
                merged.pop(key, None)

    return merged, warnings
