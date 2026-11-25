"""Tests for strict plan input and read-only diffing."""

from __future__ import annotations

import threading
from datetime import date
from typing import Any

import pytest

from garmin_cli.exceptions import GarminCliError
from garmin_cli.serializers import serialize_workout_detail
from garmin_cli.services.plan_apply import calendar_with_projections
from garmin_cli.services.training_plan import blocking_occupants, preview_training_plan, validate_training_plan
from garmin_cli.workout_builder import build_garmin_payload


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
    assert any(error.startswith("plan: unknown key 'unexpected'") for error in errors)
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


def test_plan_inline_workout_errors_read_as_paths() -> None:
    plan = _plan()
    plan["entries"] = [{"entry_id": "run-1", "date": "2026-07-10", "workout": {"title": "x"}}]
    errors = validate_training_plan(plan)
    assert any(error.startswith("plan.entries[0].workout: unknown key 'title'; allowed keys") for error in errors)
    assert "plan.entries[0].workout: 'name' is required" in errors


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


def test_preview_occupant_without_schedule_id_blocks_an_entry_without_source() -> None:
    # A missing schedule id (None) must not match the entry's missing source (None).
    result = preview_training_plan(_plan(), [{"date": "2026-07-10", "workout_id": 20, "item_type": "workout"}], {20: None})
    assert result["conflicts"] == [{"entry_id": "run-1", "reason": "destination_occupied"}]


def test_blocking_occupants_exempts_only_the_named_positive_source() -> None:
    rows = [{"workout_id": 20, "workout_schedule_id": 5}, {"workout_id": 30}]
    assert blocking_occupants(rows, 5) == [{"workout_id": 30}]
    assert blocking_occupants(rows, None) == rows


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


def test_preview_keeps_an_applied_inline_workout_with_open_target() -> None:
    # "open" is sent as no.target and reads back as no.target; a reapply must match.
    workout = {
        "name": "Easy",
        "sport": "running",
        "steps": [
            {"type": "warmup", "duration": {"type": "time", "value": 300}, "target": {"type": "open"}},
            {"type": "interval", "duration": {"type": "time", "value": 600}, "target": {"type": "no.target"}},
        ],
    }
    payload = {**build_garmin_payload(workout), "workoutId": 10}
    projection = serialize_workout_detail(payload)[0]["write_projection"]
    plan = _plan()
    plan["entries"] = [{"entry_id": "run-1", "date": "2026-07-10", "workout": workout}]

    result = preview_training_plan(
        plan,
        [{"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": 99}],
        {10: projection},
    )

    assert [operation["action"] for operation in result["operations"]] == ["keep"]
    assert result["conflicts"] == []


def test_plan_with_custom_range_targets_validates_and_reapplies_as_keep() -> None:
    workout = {
        "name": "SST",
        "sport": "cycling",
        "steps": [
            {"type": "interval", "duration": {"type": "time", "value": 600}, "target": {"type": "power.zone", "min": 240, "max": 260}},
            {"type": "recovery", "duration": {"type": "time", "value": 300}, "target": {"type": "heart.rate.zone", "min": 110, "max": 130}},
        ],
    }
    plan = _plan()
    plan["entries"] = [{"entry_id": "ride-1", "date": "2026-07-10", "workout": workout}]
    projection = serialize_workout_detail({**build_garmin_payload(workout), "workoutId": 10})[0]["write_projection"]

    result = preview_training_plan(plan, [{"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": 99}], {10: projection})

    assert validate_training_plan(plan) == []
    assert [operation["action"] for operation in result["operations"]] == ["keep"]


def test_preview_inline_match_ignores_int_float_and_null_target_differences() -> None:
    workout = {
        "name": "Cadence",
        "sport": "running",
        "steps": [
            {"type": "interval", "duration": {"type": "time", "value": 120}, "target": {"type": "cadence.zone", "min": 170, "max": 180}},
            {"type": "rest", "duration": {"type": "time", "value": 60}, "target": {"type": "open"}},
        ],
    }
    # Garmin reads values back as floats, and a rest step's target as null.
    projection = {
        "name": "Cadence",
        "sport": "running",
        "steps": [
            {"type": "interval", "duration": {"type": "time", "value": 120.0}, "target": {"type": "cadence.zone", "min": 170.0, "max": 180.0}},
            {"type": "rest", "duration": {"type": "time", "value": 60.0}, "target": None},
        ],
    }
    plan = _plan()
    plan["entries"] = [{"entry_id": "run-1", "date": "2026-07-10", "workout": workout}]

    result = preview_training_plan(plan, [{"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": 99}], {10: projection})

    assert [operation["action"] for operation in result["operations"]] == ["keep"]


@pytest.mark.parametrize(
    "row",
    [
        {"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": None, "item_type": "activity"},
        {"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": None},  # id-less schedule
    ],
)
def test_preview_keep_requires_a_positive_destination_schedule_id(row: dict) -> None:
    plan = _plan()
    plan["entries"][0].update({"move_from_schedule_id": 20, "expected_source_date": "2026-07-05"})
    source = {"date": "2026-07-05", "workout_id": 10, "workout_schedule_id": 20}

    result = preview_training_plan(plan, [source, row], {10: None})

    assert "keep" not in [operation["action"] for operation in result["operations"]]


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


def _scheduled(day: str, workout_id: int, schedule_id: int) -> dict:
    return {"date": day, "workout_id": workout_id, "workout_schedule_id": schedule_id}


def _move(entry_id: str, day: str, workout_id: int, source_id: int, source_day: str) -> dict:
    return {
        "entry_id": entry_id,
        "date": day,
        "workout_id": workout_id,
        "move_from_schedule_id": source_id,
        "expected_source_date": source_day,
    }


def test_preview_allows_swapping_two_scheduled_workouts() -> None:
    plan = _plan()
    plan["entries"] = [
        _move("tue", "2026-07-07", 20, 2, "2026-07-09"),
        _move("thu", "2026-07-09", 10, 1, "2026-07-07"),
    ]
    calendar = [_scheduled("2026-07-07", 10, 1), _scheduled("2026-07-09", 20, 2)]
    result = preview_training_plan(plan, calendar, {10: None, 20: None})
    assert result["conflicts"] == []
    assert [op["action"] for op in result["operations"]] == ["move", "move"]


def test_preview_allows_chained_shift_of_the_same_workout() -> None:
    plan = _plan()
    # Same template on both days: the Wed occupant is vacated, so it is
    # neither a conflict nor an already-applied "keep".
    plan["entries"] = [
        _move("tue-wed", "2026-07-08", 10, 1, "2026-07-07"),
        _move("wed-thu", "2026-07-09", 10, 2, "2026-07-08"),
    ]
    calendar = [_scheduled("2026-07-07", 10, 1), _scheduled("2026-07-08", 10, 2)]
    result = preview_training_plan(plan, calendar, {10: None})
    assert result["conflicts"] == []
    assert [op["action"] for op in result["operations"]] == ["move", "move"]


def test_preview_allows_removal_and_replacement_on_same_date() -> None:
    plan = _plan()
    plan["removals"] = [{"schedule_id": 77, "expected_date": "2026-07-10"}]
    result = preview_training_plan(plan, [_scheduled("2026-07-10", 55, 77)], {55: None})
    assert result["conflicts"] == []
    assert [op["action"] for op in result["operations"]] == ["schedule", "unschedule"]


def test_preview_still_flags_occupant_the_plan_does_not_vacate() -> None:
    plan = _plan()
    # The removal targets another date, and a removal whose expected date is
    # wrong is not verified, so neither vacates the destination.
    plan["removals"] = [
        {"schedule_id": 30, "expected_date": "2026-07-03"},
        {"schedule_id": 77, "expected_date": "2026-07-11"},
    ]
    calendar = [_scheduled("2026-07-03", 40, 30), _scheduled("2026-07-10", 55, 77)]
    result = preview_training_plan(plan, calendar, {40: None, 55: None})
    assert {"entry_id": "run-1", "reason": "destination_occupied"} in result["conflicts"]


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


def test_projection_templates_are_fetched_concurrently_and_missing_ones_skipped(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARMIN_CLI_FETCH_CONCURRENCY", "2")
    monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "0")
    mocker.patch(
        "garmin_cli.services.schedule_writes.get_calendar_range",
        return_value=[
            {"date": "2026-07-03", "workoutId": 30, "workoutScheduleId": 3},
            {"date": "2026-07-02", "workoutId": 20, "workoutScheduleId": 2},
            {"date": "2026-07-04", "workoutId": 40, "workoutScheduleId": 4},
        ],
    )
    # Both live templates must be in flight at once to pass the barrier.
    barrier = threading.Barrier(2, timeout=5)

    def get_workout(workout_id: int) -> dict[str, Any]:
        if workout_id == 40:
            raise GarminCliError(error="Not found.", error_code="NOT_FOUND")
        barrier.wait()
        return {
            "workoutId": workout_id,
            "workoutName": f"Run {workout_id}",
            "sportType": {"sportTypeKey": "running"},
            "workoutSegments": [],
        }

    get = mocker.patch("garmin_cli.services.plan_apply.get_workout", side_effect=get_workout)

    _, projections = calendar_with_projections(date(2026, 7, 1), date(2026, 7, 7))

    assert list(projections) == [20, 30]
    assert get.call_count == 3


def test_projection_fetch_propagates_non_not_found_errors(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.services.schedule_writes.get_calendar_range",
        return_value=[{"date": "2026-07-02", "workoutId": 20, "workoutScheduleId": 2}],
    )
    mocker.patch(
        "garmin_cli.services.plan_apply.get_workout",
        side_effect=GarminCliError(error="Server error.", error_code="SERVER_ERROR"),
    )

    with pytest.raises(GarminCliError, match="Server error"):
        calendar_with_projections(date(2026, 7, 1), date(2026, 7, 7))


def _scheduled_rows(workout_ids: list[int]) -> list[dict[str, Any]]:
    return [
        {"date": f"2026-07-0{index + 1}", "workoutId": workout_id, "workoutScheduleId": 100 + workout_id}
        for index, workout_id in enumerate(workout_ids)
    ]


def test_projection_fetch_stops_submitting_after_a_failure(mocker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GARMIN_CLI_FETCH_CONCURRENCY", "2")
    monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "0")
    mocker.patch(
        "garmin_cli.services.schedule_writes.get_calendar_range", return_value=_scheduled_rows([1, 2, 3, 4, 5])
    )
    started: list[int] = []

    def get_workout(workout_id: int) -> dict[str, Any]:
        started.append(workout_id)
        if workout_id == 1:
            threading.Event().wait(0.3)
            return {"workoutId": 1, "workoutName": "Run", "sportType": {"sportTypeKey": "running"}, "workoutSegments": []}
        raise GarminCliError(error="slow down", error_code="RATE_LIMITED")

    mocker.patch("garmin_cli.services.plan_apply.get_workout", side_effect=get_workout)

    with pytest.raises(GarminCliError, match="slow down"):
        calendar_with_projections(date(2026, 7, 1), date(2026, 7, 7))
    assert sorted(started) == [1, 2]


def test_projection_fetch_spaces_submissions_by_the_daily_call_delay(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GARMIN_CLI_DAILY_CALL_DELAY", raising=False)
    mock_sleep = mocker.patch("garmin_cli.endpoints._base.time.sleep")
    mocker.patch(
        "garmin_cli.services.schedule_writes.get_calendar_range", return_value=_scheduled_rows([1, 2, 3])
    )
    mocker.patch(
        "garmin_cli.services.plan_apply.get_workout",
        side_effect=GarminCliError(error="Not found.", error_code="NOT_FOUND"),
    )

    _, projections = calendar_with_projections(date(2026, 7, 1), date(2026, 7, 7))

    assert projections == {}
    assert [call.args[0] for call in mock_sleep.call_args_list] == pytest.approx([0.5, 0.5], abs=0.05)
