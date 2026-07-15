"""Tests for strict plan input and read-only diffing."""

from __future__ import annotations

from garmin_cli.services.training_plan import preview_training_plan, validate_training_plan


def _plan() -> dict:
    return {
        "name": "July block",
        "start_date": "2026-07-01",
        "end_date": "2026-07-14",
        "entries": [{"entry_id": "run-1", "date": "2026-07-10", "workout_id": 10}],
    }


def test_plan_schema_rejects_unknown_fields_and_same_day_entries() -> None:
    plan = _plan()
    plan["unexpected"] = True
    plan["entries"].append({"entry_id": "run-2", "date": "2026-07-10", "workout_id": 11})
    errors = validate_training_plan(plan)
    assert any("unknown field" in error for error in errors)
    assert any("multiple entries target the same date" in error for error in errors)


def test_plan_schema_rejects_noncanonical_iso_dates() -> None:
    plan = _plan()
    plan["start_date"] = "20260701"
    assert any("must be YYYY-MM-DD" in error for error in validate_training_plan(plan))


def test_plan_schema_requires_explicit_source_date_for_move() -> None:
    plan = _plan()
    plan["entries"][0]["move_from_schedule_id"] = 20
    assert any("expected_source_date" in error for error in validate_training_plan(plan))


def test_plan_schema_rejects_source_schedule_used_twice() -> None:
    plan = _plan()
    plan["entries"][0].update(
        {
            "move_from_schedule_id": 20,
            "expected_source_date": "2026-07-05",
        }
    )
    plan["removals"] = [{"schedule_id": 20, "expected_date": "2026-07-05"}]
    assert any("source schedule more than once" in error for error in validate_training_plan(plan))


def test_plan_schema_accepts_removal_only_plan() -> None:
    plan = _plan()
    plan["entries"] = []
    plan["removals"] = [{"schedule_id": 20, "expected_date": "2026-07-05"}]
    assert validate_training_plan(plan) == []


def test_plan_schema_rejects_unknown_nested_workout_fields() -> None:
    plan = _plan()
    plan["entries"] = [
        {
            "entry_id": "run-1",
            "date": "2026-07-10",
            "workout": {
                "name": "Intervals",
                "sport": "running",
                "steps": [
                    {
                        "type": "repeat",
                        "count": 3,
                        "steps": [
                            {
                                "type": "interval",
                                "duration": {"type": "time", "value": 60, "units": "seconds"},
                            }
                        ],
                    }
                ],
            },
        }
    ]
    assert any("units" in error for error in validate_training_plan(plan))


def test_preview_reports_keep_for_existing_schedule() -> None:
    result = preview_training_plan(
        _plan(),
        [{"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": 99}],
        {10: None},
    )
    assert result["complete"] is True
    assert result["operations"] == [
        {
            "entry_id": "run-1",
            "action": "keep",
            "state": "planned",
            "date": "2026-07-10",
            "workout_id": 10,
            "workout_schedule_id": 99,
        }
    ]


def test_preview_detects_changed_source() -> None:
    plan = _plan()
    plan["entries"][0].update({"move_from_schedule_id": 99, "expected_source_date": "2026-07-05"})
    result = preview_training_plan(plan, [], {})
    assert result["complete"] is False
    assert result["conflicts"] == [{"entry_id": "run-1", "reason": "source_schedule_changed"}]


def test_plan_calendar_span_includes_sources_but_stays_bounded() -> None:
    plan = _plan()
    plan["entries"][0].update(
        {
            "move_from_schedule_id": 99,
            "expected_source_date": "2025-01-01",
        }
    )
    assert any("calendar read span" in error for error in validate_training_plan(plan))


def test_preview_reapplied_move_is_a_keep_not_a_conflict() -> None:
    plan = _plan()
    plan["entries"][0].update({"move_from_schedule_id": 20, "expected_source_date": "2026-07-05"})
    # Destination already holds the workout and the source is gone: the move
    # was applied by an earlier call, so reapplying must be a no-op.
    result = preview_training_plan(
        plan,
        [{"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": 99}],
        {10: None},
    )
    assert result["complete"] is True
    assert result["operations"][0]["action"] == "keep"


def test_preview_flags_destination_occupied_by_unrelated_workout() -> None:
    plan = _plan()
    plan["entries"][0].update({"move_from_schedule_id": 20, "expected_source_date": "2026-07-05"})
    result = preview_training_plan(
        plan,
        [
            {"date": "2026-07-05", "workout_id": 10, "workout_schedule_id": 20},
            {"date": "2026-07-10", "workout_id": 55, "workout_schedule_id": 77},
        ],
        {10: None, 55: None},
    )
    assert result["complete"] is False
    assert result["conflicts"] == [{"entry_id": "run-1", "reason": "destination_occupied"}]


def test_preview_removal_of_absent_schedule_is_a_no_op() -> None:
    plan = _plan()
    plan["entries"] = []
    plan["removals"] = [{"schedule_id": 20, "expected_date": "2026-07-05"}]
    result = preview_training_plan(plan, [], {})
    assert result["complete"] is True
    assert result["operations"] == [
        {"action": "unschedule", "state": "no_op", "source_schedule_id": 20, "date": "2026-07-05"}
    ]


def test_validation_errors_are_structured() -> None:
    result = preview_training_plan({"name": ""}, [], {})
    assert result["complete"] is False
    assert all(error["error_code"] == "INVALID_INPUT" and error["message"] for error in result["errors"])
