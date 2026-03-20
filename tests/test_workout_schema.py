"""Tests for garmin_cli.workout_schema.validate_workout_input."""
from __future__ import annotations

from typing import Any

import pytest

from garmin_cli.workout_schema import validate_workout_input


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
