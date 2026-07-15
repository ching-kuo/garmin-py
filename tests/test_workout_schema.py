"""Tests for garmin_cli.workout_schema.validate_workout_input."""
from __future__ import annotations

import pytest

from garmin_cli.workout_schema import END_CONDITIONS, validate_workout_input


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_workout() -> dict:
    return {
        "name": "Morning Run",
        "sport": "running",
        "steps": [
            {
                "type": "interval",
                "duration": {"type": "time", "value": 300},
            }
        ],
    }


def _errors(data: dict, partial: bool = False) -> list:
    return validate_workout_input(data, partial=partial)


# ---------------------------------------------------------------------------
# TestValidateWorkoutInput
# ---------------------------------------------------------------------------

class TestValidateWorkoutInput:

    def test_valid_minimal_workout_no_errors(self) -> None:
        errors = _errors(_minimal_workout())
        assert errors == []

    def test_missing_name_returns_error(self) -> None:
        data = _minimal_workout()
        del data["name"]
        errors = _errors(data)
        assert len(errors) >= 1

    def test_empty_name_returns_error(self) -> None:
        data = {**_minimal_workout(), "name": ""}
        errors = _errors(data)
        assert len(errors) >= 1

    def test_name_too_long_returns_error(self) -> None:
        data = {**_minimal_workout(), "name": "x" * 257}
        errors = _errors(data)
        assert len(errors) >= 1

    def test_missing_sport_returns_error(self) -> None:
        data = _minimal_workout()
        del data["sport"]
        errors = _errors(data)
        assert len(errors) >= 1

    def test_invalid_sport_returns_error(self) -> None:
        data = {**_minimal_workout(), "sport": "skydiving"}
        errors = _errors(data)
        assert len(errors) >= 1

    @pytest.mark.parametrize(
        "sport",
        [
            "running",
            "cycling",
            "swimming",
            "walking",
            "hiking",
            "fitness_equipment",
            "multi_sport",
            "other",
        ],
    )
    def test_valid_all_sports(self, sport: str) -> None:
        data = {**_minimal_workout(), "sport": sport}
        errors = _errors(data)
        assert errors == [], f"Expected no errors for sport={sport!r}, got: {errors}"

    def test_missing_steps_returns_error(self) -> None:
        data = _minimal_workout()
        del data["steps"]
        errors = _errors(data)
        assert len(errors) >= 1

    def test_empty_steps_returns_error(self) -> None:
        data = {**_minimal_workout(), "steps": []}
        errors = _errors(data)
        assert len(errors) >= 1

    def test_invalid_step_type_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {"type": "sprint", "duration": {"type": "time", "value": 60}}
            ],
        }
        errors = _errors(data)
        assert len(errors) >= 1

    @pytest.mark.parametrize(
        "step_type",
        ["warmup", "cooldown", "interval", "recovery", "rest", "repeat"],
    )
    def test_valid_step_types(self, step_type: str) -> None:
        if step_type == "repeat":
            step = {
                "type": "repeat",
                "count": 3,
                "steps": [
                    {"type": "interval", "duration": {"type": "time", "value": 60}},
                ],
            }
        else:
            step = {"type": step_type, "duration": {"type": "time", "value": 60}}
        data = {**_minimal_workout(), "steps": [step]}
        errors = _errors(data)
        assert errors == [], f"Expected no errors for step_type={step_type!r}, got: {errors}"

    def test_step_missing_duration_returns_error(self) -> None:
        data = {**_minimal_workout(), "steps": [{"type": "interval"}]}
        errors = _errors(data)
        assert len(errors) >= 1

    def test_repeat_step_missing_count_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "repeat",
                    "steps": [
                        {"type": "interval", "duration": {"type": "time", "value": 60}}
                    ],
                }
            ],
        }
        errors = _errors(data)
        assert len(errors) >= 1

    def test_repeat_step_count_zero_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "repeat",
                    "count": 0,
                    "steps": [
                        {"type": "interval", "duration": {"type": "time", "value": 60}}
                    ],
                }
            ],
        }
        errors = _errors(data)
        assert len(errors) >= 1

    def test_repeat_step_count_100_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "repeat",
                    "count": 100,
                    "steps": [
                        {"type": "interval", "duration": {"type": "time", "value": 60}}
                    ],
                }
            ],
        }
        errors = _errors(data)
        assert len(errors) >= 1

    def test_repeat_step_count_99_valid(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "repeat",
                    "count": 99,
                    "steps": [
                        {"type": "interval", "duration": {"type": "time", "value": 60}}
                    ],
                }
            ],
        }
        errors = _errors(data)
        assert errors == []

    def test_repeat_step_missing_nested_steps_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [{"type": "repeat", "count": 3}],
        }
        errors = _errors(data)
        assert len(errors) >= 1

    def test_duration_invalid_type_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "interval",
                    "duration": {"type": "laps", "value": 2},
                }
            ],
        }
        errors = _errors(data)
        assert len(errors) >= 1

    def test_duration_missing_value_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "interval",
                    "duration": {"type": "time"},
                }
            ],
        }
        errors = _errors(data)
        assert len(errors) >= 1

    def test_target_invalid_type_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "interval",
                    "duration": {"type": "time", "value": 300},
                    "target": {"type": "invalid.target.type"},
                }
            ],
        }
        errors = _errors(data)
        assert len(errors) >= 1

    def test_zone_target_missing_zone_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "interval",
                    "duration": {"type": "time", "value": 300},
                    "target": {"type": "heart.rate.zone"},
                }
            ],
        }
        errors = _errors(data)
        assert any("missing required field 'zone'" in error for error in errors)

    def test_zone_target_non_int_zone_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "interval",
                    "duration": {"type": "time", "value": 300},
                    "target": {"type": "power.zone", "zone": "3"},
                }
            ],
        }
        errors = _errors(data)
        assert any("'zone' must be an integer" in error for error in errors)

    def test_speed_zone_target_missing_min_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "interval",
                    "duration": {"type": "time", "value": 300},
                    "target": {"type": "speed.zone", "max": 4.0},
                }
            ],
        }
        errors = _errors(data)
        assert any("missing required field 'min'" in error for error in errors)

    def test_speed_zone_target_missing_max_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "interval",
                    "duration": {"type": "time", "value": 300},
                    "target": {"type": "speed.zone", "min": 3.5},
                }
            ],
        }
        errors = _errors(data)
        assert any("missing required field 'max'" in error for error in errors)

    def test_speed_zone_target_non_numeric_bound_returns_error(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "interval",
                    "duration": {"type": "time", "value": 300},
                    "target": {"type": "speed.zone", "min": "3.5", "max": 4.0},
                }
            ],
        }
        errors = _errors(data)
        assert any("'min' must be a number" in error for error in errors)

    def test_cadence_zone_target_with_range_is_valid(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "interval",
                    "duration": {"type": "time", "value": 300},
                    "target": {"type": "cadence.zone", "min": 170, "max": 180},
                }
            ],
        }
        errors = _errors(data)
        assert errors == []

    def test_target_defaults_to_no_target_when_absent(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [
                {
                    "type": "interval",
                    "duration": {"type": "time", "value": 300},
                }
            ],
        }
        errors = _errors(data)
        assert errors == []

    def test_partial_mode_allows_missing_name(self) -> None:
        data = _minimal_workout()
        del data["name"]
        errors = _errors(data, partial=True)
        assert errors == []

    def test_partial_mode_allows_missing_sport(self) -> None:
        data = _minimal_workout()
        del data["sport"]
        errors = _errors(data, partial=True)
        assert errors == []

    def test_partial_mode_still_validates_present_fields(self) -> None:
        data = {**_minimal_workout(), "sport": "invalid_sport"}
        errors = _errors(data, partial=True)
        assert len(errors) >= 1

    def test_returns_multiple_errors(self) -> None:
        data = _minimal_workout()
        del data["name"]
        del data["sport"]
        errors = _errors(data)
        assert len(errors) >= 2

    @pytest.mark.parametrize("value", [True, False, 0, -1, float("inf"), float("nan")])
    def test_duration_requires_positive_finite_non_boolean_number(self, value: object) -> None:
        data = _minimal_workout()
        data["steps"][0]["duration"]["value"] = value
        assert any("positive finite number" in error for error in _errors(data))

    @pytest.mark.parametrize(
        ("target_type", "zone"),
        [("heart.rate.zone", 0), ("heart.rate.zone", 6), ("power.zone", 0), ("power.zone", 8), ("power.zone", True)],
    )
    def test_zone_target_bounds_are_enforced(self, target_type: str, zone: object) -> None:
        data = _minimal_workout()
        data["steps"][0]["target"] = {"type": target_type, "zone": zone}
        assert any("zone" in error and "between" in error for error in _errors(data))

    @pytest.mark.parametrize(
        "target",
        [
            {"type": "speed.zone", "min": 4.0, "max": 4.0},
            {"type": "speed.zone", "min": 4.1, "max": 4.0},
            {"type": "cadence.zone", "min": -1, "max": 180},
            {"type": "cadence.zone", "min": 170, "max": float("inf")},
        ],
    )
    def test_range_target_bounds_must_be_finite_non_negative_and_ordered(self, target: dict) -> None:
        data = _minimal_workout()
        data["steps"][0]["target"] = target
        assert _errors(data)

    def test_nested_repeat_is_rejected(self) -> None:
        data = {
            **_minimal_workout(),
            "steps": [{
                "type": "repeat",
                "count": 2,
                "steps": [{
                    "type": "repeat",
                    "count": 2,
                    "steps": [{"type": "interval", "duration": {"type": "time", "value": 60}}],
                }],
            }],
        }
        assert any("nested repeat" in error for error in _errors(data))

    def test_aggregate_workout_limits_are_enforced(self) -> None:
        data = _minimal_workout()
        data["steps"] = [{
            "type": "repeat",
            "count": 99,
            "steps": [{"type": "interval", "duration": {"type": "time", "value": 1000}}],
        }]
        assert any("total duration" in error for error in _errors(data))


def test_live_verified_end_condition_ids() -> None:
    assert END_CONDITIONS["time"] == 2
    assert END_CONDITIONS["distance"] == 3
    assert END_CONDITIONS["calories"] == 4
    assert END_CONDITIONS["power"] == 5
    assert END_CONDITIONS["heart.rate"] == 6
    assert END_CONDITIONS["iterations"] == 7


def test_description_must_be_a_string_when_supplied() -> None:
    errors = validate_workout_input(
        {
            "name": "Run",
            "sport": "running",
            "description": 5,
            "steps": [{"type": "interval", "duration": {"type": "time", "value": 300}}],
        }
    )
    assert any("'description' must be a string" in error for error in errors)
