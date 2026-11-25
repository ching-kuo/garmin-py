"""Tests for garmin_cli.workout_builder — build_garmin_payload and merge_workout_payload."""
from __future__ import annotations

import copy

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


def _existing_workout(workout_id: int = 12345, owner_id: int = 9999) -> dict:
    return {
        "workoutId": workout_id,
        "ownerId": owner_id,
        "workoutName": "Old Name",
        "description": "Old description",
        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
        "estimatedDurationInSecs": 1800,
        "estimatedDistanceInMeters": 5000,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
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
        assert ec["conditionTypeId"] == 3

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

    def test_cadence_zone_target_uses_range_values(self) -> None:
        workout = _running_workout(steps=[
            {
                "type": "interval",
                "duration": {"type": "time", "value": 300},
                "target": {"type": "cadence.zone", "min": 170, "max": 180},
            }
        ])
        payload = build_garmin_payload(workout)
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        target = step["targetType"]
        assert target["workoutTargetTypeKey"] == "cadence.zone"
        assert target["workoutTargetTypeId"] == 3
        assert step.get("targetValueOne") == 170
        assert step.get("targetValueTwo") == 180
        assert "zoneNumber" not in step

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

    def test_time_steps_contribute_estimated_duration(self) -> None:
        workout = _running_workout(steps=[
            {"type": "warmup", "duration": {"type": "time", "value": 300}},
            {"type": "interval", "duration": {"type": "time", "value": 600}},
        ])
        payload = build_garmin_payload(workout)
        assert payload["estimatedDurationInSecs"] == 900
        assert "estimatedDistanceInMeters" not in payload

    def test_distance_steps_contribute_estimated_distance(self) -> None:
        workout = _running_workout(steps=[
            {"type": "interval", "duration": {"type": "distance", "value": 400}},
            {"type": "interval", "duration": {"type": "distance", "value": 1000}},
        ])
        payload = build_garmin_payload(workout)
        assert payload["estimatedDistanceInMeters"] == 1400
        assert "estimatedDurationInSecs" not in payload

    def test_repeat_steps_contribute_estimated_metadata(self) -> None:
        workout = _running_workout(steps=[
            {
                "type": "repeat",
                "count": 3,
                "steps": [
                    {"type": "interval", "duration": {"type": "time", "value": 120}},
                    {"type": "interval", "duration": {"type": "distance", "value": 400}},
                ],
            }
        ])
        payload = build_garmin_payload(workout)
        assert payload["estimatedDurationInSecs"] == 360
        assert payload["estimatedDistanceInMeters"] == 1200

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

    def test_updates_segment_sport_type_when_only_sport_changes(self) -> None:
        existing = _existing_workout()
        result, _ = merge_workout_payload(existing, {"sport": "cycling"})
        assert result["workoutSegments"][0]["sportType"]["sportTypeKey"] == "cycling"

    def test_preserves_multi_segment_sport_types_on_sport_only_update(self) -> None:
        existing = _existing_workout()
        existing["sportType"] = {"sportTypeId": 5, "sportTypeKey": "multi_sport"}
        existing["workoutSegments"] = [
            {
                "segmentOrder": 1,
                "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                "workoutSteps": [],
            },
            {
                "segmentOrder": 2,
                "sportType": {"sportTypeId": 2, "sportTypeKey": "cycling"},
                "workoutSteps": [],
            },
        ]
        result, _ = merge_workout_payload(existing, {"sport": "multi_sport"})
        assert result["workoutSegments"][0]["sportType"]["sportTypeKey"] == "running"
        assert result["workoutSegments"][1]["sportType"]["sportTypeKey"] == "cycling"

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

    def test_recomputes_estimated_duration_when_steps_change(self) -> None:
        existing = _existing_workout()
        result, _ = merge_workout_payload(
            existing,
            {
                "steps": [
                    {"type": "interval", "duration": {"type": "time", "value": 300}},
                    {"type": "cooldown", "duration": {"type": "time", "value": 120}},
                ]
            },
        )
        assert result["estimatedDurationInSecs"] == 420

    def test_recomputes_estimated_distance_when_steps_change(self) -> None:
        existing = _existing_workout()
        result, _ = merge_workout_payload(
            existing,
            {"steps": [{"type": "interval", "duration": {"type": "distance", "value": 1600}}]},
        )
        assert result["estimatedDistanceInMeters"] == 1600

    def test_clears_stale_distance_when_steps_change_to_time_only(self) -> None:
        existing = _existing_workout()
        result, _ = merge_workout_payload(
            existing,
            {"steps": [{"type": "interval", "duration": {"type": "time", "value": 300}}]},
        )
        assert "estimatedDistanceInMeters" not in result

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

    def test_steps_update_keeps_sub_sport_outside_sport_types(self) -> None:
        existing = _existing_workout()
        trail = {"sportTypeId": 1, "sportTypeKey": "trail_running", "displayOrder": 1}
        existing["sportType"] = dict(trail)
        steps = [{"type": "interval", "duration": {"type": "time", "value": 300}}]
        result, _ = merge_workout_payload(existing, {"steps": steps})
        assert result["sportType"] == trail
        assert result["workoutSegments"][0]["sportType"] == trail

    def test_steps_update_without_stored_sport_requires_sport(self) -> None:
        import pytest

        from garmin_cli.exceptions import GarminCliError

        existing = _existing_workout()
        del existing["sportType"]
        steps = [{"type": "interval", "duration": {"type": "time", "value": 300}}]
        with pytest.raises(GarminCliError, match="include 'sport'") as excinfo:
            merge_workout_payload(existing, {"steps": steps})
        assert excinfo.value.error_code == "INVALID_INPUT"
        result, _ = merge_workout_payload(existing, {"steps": steps, "sport": "cycling"})
        assert result["workoutSegments"][0]["sportType"]["sportTypeKey"] == "cycling"

    def test_projected_steps_only_update_of_stored_fixture(self) -> None:
        import json
        from pathlib import Path

        from garmin_cli.serializers import serialize_workout_detail
        from garmin_cli.workout_schema import validate_workout_input

        fixture = Path(__file__).parent / "fixtures/backend/get_workout/get_workout__workout_id=id-a20c2562.json"
        existing = json.loads(fixture.read_text())
        # The stored sportType has a key but no id; the id is filled from SPORT_TYPES.
        update = {"steps": serialize_workout_detail(existing)[0]["write_projection"]["steps"]}
        assert validate_workout_input(update, partial=True) == []
        result, _ = merge_workout_payload(existing, update)
        assert result["sportType"] == {"sportTypeId": 1, "sportTypeKey": "running"}
        assert result["workoutSegments"][0]["sportType"] == result["sportType"]

    def test_steps_update_backfills_invalid_id_for_known_sport(self) -> None:
        steps = [{"type": "interval", "duration": {"type": "time", "value": 300}}]
        for bad_id in (0, "1", None, True):
            existing = {**_existing_workout(), "sportType": {"sportTypeId": bad_id, "sportTypeKey": "cycling"}}
            result, _ = merge_workout_payload(existing, {"steps": steps})
            assert result["sportType"] == {"sportTypeId": 2, "sportTypeKey": "cycling"}

    def test_steps_update_rejects_unusable_stored_sport(self) -> None:
        import pytest

        from garmin_cli.exceptions import GarminCliError

        steps = [{"type": "interval", "duration": {"type": "time", "value": 300}}]
        for sport_type in ({"sportTypeKey": ""}, {"sportTypeKey": "trail_running"}, {"sportTypeId": 1}):
            existing = {**_existing_workout(), "sportType": sport_type}
            with pytest.raises(GarminCliError, match="include 'sport'"):
                merge_workout_payload(existing, {"steps": steps})

    def test_partial_update_name_only(self) -> None:
        existing = _existing_workout()
        result, _ = merge_workout_payload(existing, {"name": "Only Name Changed"})
        assert result["workoutName"] == "Only Name Changed"
        # Sport preserved from existing
        assert result["sportType"]["sportTypeKey"] == "running"
