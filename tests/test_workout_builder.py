"""Tests for garmin_cli.workout_builder — build_garmin_payload and merge_workout_payload."""
from __future__ import annotations

import copy
from typing import Any

import pytest

from garmin_cli.workout_builder import build_garmin_payload, merge_workout_payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _running_workout(steps: list | None = None) -> dict:
    return {
        "name": "Morning Run",
        "sport": "running",
        "steps": steps
        or [
            {
                "type": "warmup",
                "duration": {"type": "time", "value": 300},
            }
        ],
    }


def _interval_step(
    duration_type: str = "time",
    duration_value: int = 600,
    target: dict | None = None,
) -> dict:
    step: dict = {
        "type": "interval",
        "duration": {"type": duration_type, "value": duration_value},
    }
    if target is not None:
        step["target"] = target
    return step


def _existing_workout(workout_id: int = 12345, owner_id: int = 9999) -> dict:
    return {
        "workoutId": workout_id,
        "ownerId": owner_id,
        "workoutName": "Old Name",
        "description": "Old description",
        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "workoutSteps": [],
            }
        ],
    }


# ---------------------------------------------------------------------------
# TestBuildGarminPayload
# ---------------------------------------------------------------------------

class TestBuildGarminPayload:

    def test_sets_workout_name(self) -> None:
        payload = build_garmin_payload(_running_workout())
        assert payload["workoutName"] == "Morning Run"

    def test_sets_sport_type_for_running(self) -> None:
        payload = build_garmin_payload(_running_workout())
        sport = payload["sportType"]
        assert sport["sportTypeKey"] == "running"
        assert isinstance(sport["sportTypeId"], int)

    def test_has_workout_segments(self) -> None:
        payload = build_garmin_payload(_running_workout())
        assert "workoutSegments" in payload
        assert isinstance(payload["workoutSegments"], list)
        assert len(payload["workoutSegments"]) >= 1

    def test_step_order_starts_at_1(self) -> None:
        payload = build_garmin_payload(_running_workout())
        segments = payload["workoutSegments"]
        steps = segments[0]["workoutSteps"]
        assert steps[0]["stepOrder"] == 1

    def test_warmup_step_type_id(self) -> None:
        workout = _running_workout(steps=[
            {"type": "warmup", "duration": {"type": "time", "value": 300}}
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        assert step["stepType"]["stepTypeKey"] == "warmup"
        assert step["stepType"]["stepTypeId"] == 1

    def test_time_duration_end_condition(self) -> None:
        workout = _running_workout(steps=[
            {"type": "interval", "duration": {"type": "time", "value": 600}}
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        ec = step["endCondition"]
        assert ec["conditionTypeKey"] == "time"
        assert ec["conditionTypeId"] == 2
        assert step["endConditionValue"] == 600

    def test_distance_duration_end_condition(self) -> None:
        workout = _running_workout(steps=[
            {"type": "interval", "duration": {"type": "distance", "value": 1000}}
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        ec = step["endCondition"]
        assert ec["conditionTypeKey"] == "distance"
        assert ec["conditionTypeId"] == 1

    def test_no_target_type(self) -> None:
        workout = _running_workout(steps=[
            {
                "type": "interval",
                "duration": {"type": "time", "value": 300},
                "target": {"type": "no.target"},
            }
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        target = step["targetType"]
        assert target["workoutTargetTypeKey"] == "no.target"
        assert target["workoutTargetTypeId"] == 1

    def test_heart_rate_zone_target(self) -> None:
        workout = _running_workout(steps=[
            {
                "type": "interval",
                "duration": {"type": "time", "value": 300},
                "target": {"type": "heart.rate.zone", "zone": 3},
            }
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        target = step["targetType"]
        assert target["workoutTargetTypeId"] == 4
        assert step.get("zoneNumber") == 3

    def test_speed_zone_target_maps_to_pace_zone(self) -> None:
        workout = _running_workout(steps=[
            {
                "type": "interval",
                "duration": {"type": "time", "value": 300},
                "target": {
                    "type": "speed.zone",
                    "min": 3.0,
                    "max": 4.0,
                },
            }
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        target = step["targetType"]
        # user-facing "speed.zone" maps to Garmin "pace.zone" (ID 6)
        assert target["workoutTargetTypeKey"] == "pace.zone"
        assert target["workoutTargetTypeId"] == 6
        assert step.get("targetValueOne") is not None
        assert step.get("targetValueTwo") is not None

    def test_power_zone_target(self) -> None:
        workout = _running_workout(steps=[
            {
                "type": "interval",
                "duration": {"type": "time", "value": 300},
                "target": {"type": "power.zone", "zone": 3},
            }
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        target = step["targetType"]
        assert target["workoutTargetTypeId"] == 2

    def test_repeat_step_uses_repeat_group_dto(self) -> None:
        workout = _running_workout(steps=[
            {
                "type": "repeat",
                "count": 4,
                "steps": [
                    {"type": "interval", "duration": {"type": "time", "value": 300}},
                    {"type": "recovery", "duration": {"type": "time", "value": 90}},
                ],
            }
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        assert step["type"] == "RepeatGroupDTO"

    def test_repeat_step_has_nested_steps(self) -> None:
        workout = _running_workout(steps=[
            {
                "type": "repeat",
                "count": 4,
                "steps": [
                    {"type": "interval", "duration": {"type": "time", "value": 300}},
                    {"type": "recovery", "duration": {"type": "time", "value": 90}},
                ],
            }
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        nested = step.get("workoutSteps") or step.get("steps")
        assert nested is not None
        assert len(nested) == 2

    def test_repeat_step_count_in_end_condition(self) -> None:
        workout = _running_workout(steps=[
            {
                "type": "repeat",
                "count": 4,
                "steps": [
                    {"type": "interval", "duration": {"type": "time", "value": 300}},
                ],
            }
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        ec = step["endCondition"]
        assert ec["conditionTypeKey"] == "iterations"
        assert step["endConditionValue"] == 4

    def test_default_target_when_absent(self) -> None:
        workout = _running_workout(steps=[
            {"type": "interval", "duration": {"type": "time", "value": 300}}
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        target = step["targetType"]
        assert target["workoutTargetTypeKey"] == "no.target"

    def test_input_not_mutated(self) -> None:
        original = _running_workout()
        original_copy = copy.deepcopy(original)
        build_garmin_payload(original)
        assert original == original_copy

    def test_step_has_executable_step_dto_type(self) -> None:
        workout = _running_workout(steps=[
            {"type": "interval", "duration": {"type": "time", "value": 300}}
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        assert step["type"] == "ExecutableStepDTO"

    def test_cycling_sport_type_id(self) -> None:
        workout = {**_running_workout(), "sport": "cycling"}
        payload = build_garmin_payload(workout)
        assert payload["sportType"]["sportTypeId"] == 2

    def test_description_included_when_present(self) -> None:
        workout = {**_running_workout(), "description": "Easy recovery run"}
        payload = build_garmin_payload(workout)
        assert payload.get("description") == "Easy recovery run"

    def test_sport_type_has_required_keys(self) -> None:
        payload = build_garmin_payload(_running_workout())
        sport = payload["sportType"]
        assert "sportTypeId" in sport
        assert "sportTypeKey" in sport


# ---------------------------------------------------------------------------
# TestMergeWorkoutPayload
# ---------------------------------------------------------------------------

class TestMergeWorkoutPayload:

    def test_preserves_workout_id(self) -> None:
        existing = _existing_workout(workout_id=12345)
        result, _ = merge_workout_payload(existing, {"name": "New Name"})
        assert result["workoutId"] == 12345

    def test_preserves_owner_id(self) -> None:
        existing = _existing_workout(owner_id=9999)
        result, _ = merge_workout_payload(existing, {"name": "New Name"})
        assert result["ownerId"] == 9999

    def test_overwrites_name_when_provided(self) -> None:
        existing = _existing_workout()
        result, _ = merge_workout_payload(existing, {"name": "Updated Name"})
        assert result["workoutName"] == "Updated Name"

    def test_overwrites_sport_when_provided(self) -> None:
        existing = _existing_workout()
        result, _ = merge_workout_payload(existing, {"sport": "cycling"})
        assert result["sportType"]["sportTypeKey"] == "cycling"

    def test_overwrites_description_when_provided(self) -> None:
        existing = _existing_workout()
        result, _ = merge_workout_payload(existing, {"description": "New description"})
        assert result.get("description") == "New description"

    def test_replaces_segments_when_steps_provided(self) -> None:
        existing = _existing_workout()
        new_input = {
            "steps": [
                {"type": "interval", "duration": {"type": "time", "value": 300}}
            ]
        }
        result, _ = merge_workout_payload(existing, new_input)
        segments = result["workoutSegments"]
        assert len(segments) >= 1

    def test_preserves_existing_segments_when_no_steps(self) -> None:
        existing = _existing_workout()
        original_segments = copy.deepcopy(existing["workoutSegments"])
        result, _ = merge_workout_payload(existing, {"name": "New Name"})
        assert result["workoutSegments"] == original_segments

    def test_passes_through_unknown_fields(self) -> None:
        existing = {**_existing_workout(), "_unknownField": "preserved"}
        result, _ = merge_workout_payload(existing, {"name": "New Name"})
        assert result.get("_unknownField") == "preserved"

    def test_returns_warnings_for_read_only_user_input(self) -> None:
        existing = _existing_workout()
        user_input = {"name": "New Name", "workoutId": 99999}
        _, warnings = merge_workout_payload(existing, user_input)
        assert len(warnings) >= 1

    def test_read_only_field_from_existing_preserved_when_user_supplies_it(self) -> None:
        existing = _existing_workout(workout_id=12345)
        # User tries to override workoutId — must be ignored, existing value preserved
        user_input = {"name": "New Name", "workoutId": 99999}
        result, warnings = merge_workout_payload(existing, user_input)
        assert result["workoutId"] == 12345
        assert len(warnings) >= 1

    def test_no_warnings_for_clean_input(self) -> None:
        existing = _existing_workout()
        user_input = {"name": "New Name", "sport": "cycling"}
        _, warnings = merge_workout_payload(existing, user_input)
        assert warnings == []

    def test_partial_update_name_only(self) -> None:
        existing = _existing_workout()
        result, _ = merge_workout_payload(existing, {"name": "Only Name Changed"})
        assert result["workoutName"] == "Only Name Changed"
        # Sport preserved from existing
        assert result["sportType"]["sportTypeKey"] == "running"
