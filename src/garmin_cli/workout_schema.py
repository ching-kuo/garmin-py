"""Constants and validation for the simplified LLM-friendly workout input schema."""
from __future__ import annotations

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
    "distance": 1,
    "time": 2,
    "heart.rate": 3,
    "calories": 4,
    "cadence": 5,
    "power": 6,
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


def _validate_step(step: object, index: int, prefix: str) -> list[str]:
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
        count = step.get("count")
        if count is None:
            errors.append(f"{prefix}[{index}]: repeat step missing required field 'count'")
        elif not isinstance(count, int) or count < 1 or count > 99:
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
                errors.extend(_validate_step(nested, j, f"{prefix}[{index}].steps"))
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
        else:
            errors.append(f"{prefix}[{index}]: 'duration' must be a dict")

    target = step.get("target")
    if target is not None:
        if not isinstance(target, dict):
            errors.append(f"{prefix}[{index}]: 'target' must be a dict")
        else:
            target_type = target.get("type")
            if target_type not in TARGET_TYPES:
                errors.append(
                    f"{prefix}[{index}]: invalid target type {target_type!r}; "
                    f"must be one of {sorted(TARGET_TYPES)}"
                )

    return errors


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

    return errors
