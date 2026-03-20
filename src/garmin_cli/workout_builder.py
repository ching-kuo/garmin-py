"""Transform simplified LLM-friendly workout schema to Garmin API format."""
from __future__ import annotations

import copy

from garmin_cli.exceptions import GarminCliError
from garmin_cli.workout_schema import END_CONDITIONS, SPORT_TYPES, STEP_TYPES, TARGET_TYPES

# Read-only fields from the Garmin API that must never be overwritten by user input.
_READ_ONLY_FIELDS = frozenset(
    {"workoutId", "ownerId", "createdDate", "updatedDate", "consumer", "atpPlanId"}
)

# "speed.zone" in user input maps to Garmin's "pace.zone" with ID 6.
_SPEED_ZONE_KEY = "pace.zone"
_SPEED_ZONE_ID = 6

_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}

# Zone-based target types (use zoneNumber)
_ZONE_TARGETS = {"heart.rate.zone", "power.zone", "cadence.zone"}

# Range-based target types (use targetValueOne / targetValueTwo)
_RANGE_TARGETS = {"speed.zone"}


def _build_target(target: dict | None) -> tuple[dict, dict]:
    """Build (targetType_dict, extra_fields_dict) from a target spec.

    Returns a tuple of:
        - targetType dict (workoutTargetTypeId, workoutTargetTypeKey)
        - extra fields to merge into the step (e.g. zoneNumber, targetValueOne/Two)
    """
    if target is None:
        return dict(_NO_TARGET), {}

    target_type_key = target.get("type", "no.target")

    if target_type_key == "speed.zone":
        target_type = {
            "workoutTargetTypeId": _SPEED_ZONE_ID,
            "workoutTargetTypeKey": _SPEED_ZONE_KEY,
        }
        extra: dict = {}
        if "min" in target:
            extra["targetValueOne"] = target["min"]
        if "max" in target:
            extra["targetValueTwo"] = target["max"]
        return target_type, extra

    if target_type_key in _ZONE_TARGETS:
        type_id = TARGET_TYPES.get(target_type_key, 1)
        target_type = {
            "workoutTargetTypeId": type_id,
            "workoutTargetTypeKey": target_type_key,
        }
        extra = {}
        if "zone" in target:
            extra["zoneNumber"] = target["zone"]
        return target_type, extra

    # Generic (no.target, open, etc.)
    type_id = TARGET_TYPES.get(target_type_key, 1)
    target_type = {
        "workoutTargetTypeId": type_id,
        "workoutTargetTypeKey": target_type_key,
    }
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

    # Executable step
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


def build_garmin_payload(input_data: dict) -> dict:
    """Transform simplified workout input to Garmin API payload.

    Pure function — does not mutate input_data.

    Args:
        input_data: Simplified workout dict with keys: name, sport, steps,
                    and optionally description.

    Returns:
        Garmin API format dict.
    """
    sport_key = input_data["sport"]
    sport_type = _build_sport_type(sport_key)

    workout_steps = [
        _build_step(step, i + 1) for i, step in enumerate(input_data["steps"])
    ]

    payload: dict = {
        "workoutName": input_data["name"],
        "sportType": sport_type,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": sport_type,
                "workoutSteps": workout_steps,
            }
        ],
    }

    if "description" in input_data:
        payload["description"] = input_data["description"]

    return payload


def merge_workout_payload(existing: dict, user_input: dict) -> tuple[dict, list[str]]:
    """Merge user changes into an existing Garmin workout payload.

    Pure function — does not mutate either input.

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
    for field in _READ_ONLY_FIELDS:
        if field in user_input:
            warnings.append(
                f"Field '{field}' is read-only and cannot be modified; existing value preserved."
            )

    # Apply user changes (mapped to Garmin API field names)
    if "name" in user_input:
        merged["workoutName"] = user_input["name"]

    if "sport" in user_input:
        merged["sportType"] = _build_sport_type(user_input["sport"])

    if "description" in user_input:
        merged["description"] = user_input["description"]

    if "steps" in user_input:
        # Rebuild segments entirely from user's steps, preserving name/sport from merged
        sport_key = merged["sportType"]["sportTypeKey"]
        workout_name = merged.get("workoutName", "")
        temp_input = {
            "name": workout_name,
            "sport": sport_key,
            "steps": user_input["steps"],
        }
        rebuilt = build_garmin_payload(temp_input)
        merged["workoutSegments"] = rebuilt["workoutSegments"]

    # Ensure read-only fields from existing are not overwritten
    for field in _READ_ONLY_FIELDS:
        if field in existing:
            merged[field] = existing[field]

    return merged, warnings
