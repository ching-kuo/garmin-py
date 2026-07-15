"""Constants and validation for the simplified LLM-friendly workout input schema."""
from __future__ import annotations

import math

SPORT_TYPES: dict[str, int] = {
    "running": 1,
    "cycling": 2,
    "swimming": 3,
    "walking": 4,
    "multi_sport": 5,
    "fitness_equipment": 6,
    "hiking": 7,
    "other": 8,
}

STEP_TYPES: dict[str, int] = {
    "warmup": 1,
    "cooldown": 2,
    "interval": 3,
    "recovery": 4,
    "rest": 5,
    "repeat": 6,
}

END_CONDITIONS: dict[str, int] = {
    "distance": 3,
    "time": 2,
    "heart.rate": 6,
    "calories": 4,
    "power": 5,
    "iterations": 7,
}

TARGET_TYPES: dict[str, int] = {
    "no.target": 1,
    "power.zone": 2,
    "cadence.zone": 3,
    "heart.rate.zone": 4,
    "speed.zone": 5,
    "open": 6,
}

_VALID_DURATION_TYPES = {"time", "distance"}

# Zone-based target types (use zoneNumber)
ZONE_TARGETS = frozenset({"heart.rate.zone", "power.zone"})

# Range-based target types (use targetValueOne / targetValueTwo)
RANGE_TARGETS = frozenset({"speed.zone", "cadence.zone"})

_ZONE_LIMITS = {
    "heart.rate.zone": 5,
    "power.zone": 7,
}

# Guardrails for payload size and accidental unit mistakes in AI-generated
# workouts. Values are deliberately generous enough for ultra-endurance plans
# while preventing a malformed repeat from producing an unbounded payload.
_MAX_EXPANDED_STEPS = 1_000
_MAX_TOTAL_DURATION_SECONDS = 86_400
_MAX_TOTAL_DISTANCE_METERS = 1_000_000


def _is_finite_number(value: object) -> bool:
    """Return whether ``value`` is a finite numeric scalar (not ``bool``)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_target(target: object, index: int, prefix: str) -> list[str]:
    """Validate target-specific required fields for a step."""
    errors: list[str] = []

    if not isinstance(target, dict):
        errors.append(f"{prefix}[{index}]: 'target' must be a dict")
        return errors

    target_type = target.get("type")
    if target_type not in TARGET_TYPES:
        errors.append(
            f"{prefix}[{index}]: invalid target type {target_type!r}; "
            f"must be one of {sorted(TARGET_TYPES)}"
        )
        return errors

    if target_type in ZONE_TARGETS:
        zone = target.get("zone")
        if zone is None:
            errors.append(f"{prefix}[{index}]: target missing required field 'zone'")
        elif not isinstance(zone, int):
            errors.append(f"{prefix}[{index}]: target 'zone' must be an integer")
        elif isinstance(zone, bool) or not 1 <= zone <= _ZONE_LIMITS[target_type]:
            errors.append(
                f"{prefix}[{index}]: target 'zone' must be between 1 and "
                f"{_ZONE_LIMITS[target_type]}"
            )

    if target_type in RANGE_TARGETS:
        min_value = target.get("min")
        max_value = target.get("max")
        if min_value is None:
            errors.append(f"{prefix}[{index}]: target missing required field 'min'")
        elif not _is_finite_number(min_value):
            errors.append(f"{prefix}[{index}]: target 'min' must be a number")
        if max_value is None:
            errors.append(f"{prefix}[{index}]: target missing required field 'max'")
        elif not _is_finite_number(max_value):
            errors.append(f"{prefix}[{index}]: target 'max' must be a number")
        elif isinstance(min_value, (int, float)) and not isinstance(min_value, bool):
            if min_value < 0:
                errors.append(f"{prefix}[{index}]: target 'min' must be non-negative")
            if max_value < 0:
                errors.append(f"{prefix}[{index}]: target 'max' must be non-negative")
            if (
                _is_finite_number(min_value)
                and _is_finite_number(max_value)
                and min_value >= max_value
            ):
                errors.append(f"{prefix}[{index}]: target 'min' must be less than 'max'")

    return errors


def _validate_step(
    step: object,
    index: int,
    prefix: str,
    repeat_depth: int = 0,
) -> list[str]:
    """Validate a single step dict. Returns list of error strings."""
    errors: list[str] = []

    if not isinstance(step, dict):
        errors.append(f"{prefix}[{index}]: step must be a dict")
        return errors

    step_type = step.get("type")
    if step_type not in STEP_TYPES:
        errors.append(
            f"{prefix}[{index}]: invalid step type {step_type!r}; "
            f"must be one of {sorted(STEP_TYPES)}"
        )

    if step_type == "repeat":
        if repeat_depth:
            errors.append(f"{prefix}[{index}]: nested repeat steps are not supported")
        count = step.get("count")
        if count is None:
            errors.append(f"{prefix}[{index}]: repeat step missing required field 'count'")
        elif isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > 99:
            errors.append(
                f"{prefix}[{index}]: repeat 'count' must be an integer between 1 and 99, got {count!r}"
            )

        nested_steps = step.get("steps")
        if nested_steps is None:
            errors.append(f"{prefix}[{index}]: repeat step missing required field 'steps'")
        elif not isinstance(nested_steps, list) or len(nested_steps) == 0:
            errors.append(f"{prefix}[{index}]: repeat 'steps' must be a non-empty list")
        else:
            for j, nested in enumerate(nested_steps):
                errors.extend(
                    _validate_step(
                        nested,
                        j,
                        f"{prefix}[{index}].steps",
                        repeat_depth + 1,
                    )
                )
    else:
        duration = step.get("duration")
        if duration is None:
            errors.append(f"{prefix}[{index}]: non-repeat step missing required field 'duration'")
        elif isinstance(duration, dict):
            dur_type = duration.get("type")
            if dur_type not in _VALID_DURATION_TYPES:
                errors.append(
                    f"{prefix}[{index}]: duration type {dur_type!r} invalid; "
                    f"must be one of {sorted(_VALID_DURATION_TYPES)}"
                )
            if "value" not in duration:
                errors.append(f"{prefix}[{index}]: duration missing required field 'value'")
            elif not _is_finite_number(duration["value"]) or duration["value"] <= 0:
                errors.append(
                    f"{prefix}[{index}]: duration 'value' must be a positive finite number"
                )
        else:
            errors.append(f"{prefix}[{index}]: 'duration' must be a dict")

    target = step.get("target")
    if target is not None:
        errors.extend(_validate_target(target, index, prefix))

    return errors


def _expanded_metrics(steps: list[object]) -> tuple[int, float, float]:
    """Return expanded step count, seconds, and meters for valid-shaped input."""
    count = 0
    duration_seconds = 0.0
    distance_meters = 0.0
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "repeat":
            nested = step.get("steps")
            multiplier = step.get("count")
            if isinstance(nested, list) and isinstance(multiplier, int) and not isinstance(multiplier, bool):
                nested_count, nested_seconds, nested_meters = _expanded_metrics(nested)
                count += nested_count * multiplier
                duration_seconds += nested_seconds * multiplier
                distance_meters += nested_meters * multiplier
            continue
        count += 1
        duration = step.get("duration")
        if not isinstance(duration, dict):
            continue
        value = duration.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            continue
        if duration.get("type") == "time":
            duration_seconds += value
        elif duration.get("type") == "distance":
            distance_meters += value
    return count, duration_seconds, distance_meters


def validate_workout_input(data: dict, partial: bool = False) -> list[str]:
    """Validate simplified workout input.

    Args:
        data: Workout input dict.
        partial: When True, only fields present are validated (missing top-level
                 fields are not reported as errors).

    Returns:
        List of error strings. Empty list means valid.
    """
    errors: list[str] = []

    name = data.get("name")
    if not partial or "name" in data:
        if name is None:
            errors.append("'name' is required")
        elif not isinstance(name, str) or len(name) == 0:
            errors.append("'name' must be a non-empty string")
        elif len(name) > 256:
            errors.append("'name' must be at most 256 characters")

    if "description" in data and data["description"] is not None and not isinstance(data["description"], str):
        errors.append("'description' must be a string when supplied")

    sport = data.get("sport")
    if not partial or "sport" in data:
        if sport is None:
            errors.append("'sport' is required")
        elif sport not in SPORT_TYPES:
            errors.append(
                f"'sport' {sport!r} is invalid; must be one of {sorted(SPORT_TYPES)}"
            )

    steps = data.get("steps")
    if not partial or "steps" in data:
        if steps is None:
            errors.append("'steps' is required")
        elif not isinstance(steps, list) or len(steps) == 0:
            errors.append("'steps' must be a non-empty list")
        else:
            for i, step in enumerate(steps):
                errors.extend(_validate_step(step, i, "steps"))
            expanded_count, total_duration, total_distance = _expanded_metrics(steps)
            if expanded_count > _MAX_EXPANDED_STEPS:
                errors.append(
                    f"expanded step count must not exceed {_MAX_EXPANDED_STEPS} (got {expanded_count})"
                )
            if total_duration > _MAX_TOTAL_DURATION_SECONDS:
                errors.append(
                    "total duration must not exceed "
                    f"{_MAX_TOTAL_DURATION_SECONDS} seconds (got {total_duration:g})"
                )
            if total_distance > _MAX_TOTAL_DISTANCE_METERS:
                errors.append(
                    "total distance must not exceed "
                    f"{_MAX_TOTAL_DISTANCE_METERS} meters (got {total_distance:g})"
                )

    return errors
