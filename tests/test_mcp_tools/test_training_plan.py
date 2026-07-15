"""MCP tests for stateless preview/apply planning workflows."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


def _plan() -> dict:
    return {
        "name": "July block",
        "start_date": "2026-07-01",
        "end_date": "2026-07-14",
        "entries": [{"entry_id": "run-1", "date": "2026-07-10", "workout_id": 10}],
    }


def _annotations(server: Any, name: str) -> Any:
    return server._tool_manager.get_tool(name).annotations


def test_plan_tool_annotations() -> None:
    server = create_mcp_server(_config())
    assert _annotations(server, "training_plan_preview").read_only_hint is True
    assert _annotations(server, "training_plan_apply").destructive_hint is True
    assert _annotations(server, "training_plan_reschedule").destructive_hint is True


def test_preview_is_read_only_and_returns_keep(mocker: Any) -> None:
    auth = mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    calendar = mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_calendar_range",
        return_value=[{"date": "2026-07-10", "workoutId": 10, "workoutScheduleId": 99}],
    )
    get = mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_workout",
        return_value={"workoutId": 10, "workoutName": "Run", "sportType": {"sportTypeKey": "running"}, "workoutSegments": []},
    )
    create = mocker.patch("garmin_cli.mcp_tools.training_plan.create_workout")
    server = create_mcp_server(_config())

    result = _call(server, "training_plan_preview", {"plan": _plan()})

    assert result["complete"] is True, result
    assert result["operations"][0]["action"] == "keep"
    auth.assert_called_once()
    calendar.assert_called_once()
    get.assert_called_once_with(10)
    create.assert_not_called()


def test_preview_calendar_read_includes_expected_source_date(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    calendar = mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_calendar_range",
        return_value=[{"date": "2026-06-30", "workoutId": 10, "workoutScheduleId": 99}],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_workout",
        return_value={
            "workoutId": 10,
            "workoutName": "Run",
            "sportType": {"sportTypeKey": "running"},
            "workoutSegments": [],
        },
    )
    plan = _plan()
    plan["entries"][0].update(
        {
            "move_from_schedule_id": 99,
            "expected_source_date": "2026-06-30",
        }
    )
    server = create_mcp_server(_config())

    result = _call(server, "training_plan_preview", {"plan": plan})

    assert result["complete"] is True
    calendar.assert_called_once()
    assert calendar.call_args.args[0].isoformat() == "2026-06-30"


def test_apply_schedules_then_verifies_before_returning_success(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_calendar_range",
        side_effect=[[], [], [{"date": "2026-07-10", "workoutId": 10, "workoutScheduleId": 99}]],
    )
    schedule = mocker.patch(
        "garmin_cli.mcp_tools.training_plan.schedule_workout",
        return_value={"workoutScheduleId": 99},
    )
    unschedule = mocker.patch("garmin_cli.mcp_tools.training_plan.unschedule_workout")
    server = create_mcp_server(_config())

    result = _call(server, "training_plan_apply", {"plan": _plan()})

    assert result["complete"] is True
    assert result["outcome"] == "complete"
    assert result["operations"] == [
        {
            "entry_id": "run-1",
            "action": "schedule",
            "date": "2026-07-10",
            "workout_id": 10,
            "workout_schedule_id": 99,
            "state": "verified",
        }
    ]
    schedule.assert_called_once()
    unschedule.assert_not_called()


def test_apply_cleans_returned_schedule_when_verification_fails(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_calendar_range",
        side_effect=[[], [], []],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.schedule_workout",
        return_value={"workoutScheduleId": 99},
    )
    unschedule = mocker.patch("garmin_cli.mcp_tools.training_plan.unschedule_workout")
    server = create_mcp_server(_config())

    result = _call(server, "training_plan_apply", {"plan": _plan()})

    assert result["complete"] is False
    assert result["outcome"] == "compensated"
    unschedule.assert_called_once_with(99)


def test_apply_keeps_new_template_if_schedule_cleanup_fails(mocker: Any) -> None:
    from garmin_cli.exceptions import GarminCliError

    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_calendar_range",
        side_effect=[[], [], []],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.create_workout",
        return_value={"workoutId": 10},
    )
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.schedule_workout",
        return_value={"workoutScheduleId": 99},
    )
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.unschedule_workout",
        side_effect=GarminCliError("cleanup failed", "SERVER_ERROR"),
    )
    delete = mocker.patch("garmin_cli.mcp_tools.training_plan.delete_workout")
    plan = {
        "name": "July block",
        "start_date": "2026-07-01",
        "end_date": "2026-07-14",
        "entries": [
            {
                "entry_id": "run-1",
                "date": "2026-07-10",
                "workout": {
                    "name": "Easy Run",
                    "sport": "running",
                    "steps": [{"type": "interval", "duration": {"type": "time", "value": 300}}],
                },
            }
        ],
    }
    server = create_mcp_server(_config())

    result = _call(server, "training_plan_apply", {"plan": plan})

    assert result["outcome"] == "unknown"
    delete.assert_not_called()


def test_apply_equivalent_inline_workout_is_a_no_op(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    inline = {
        "name": "Easy Run",
        "sport": "running",
        "steps": [{"type": "interval", "duration": {"type": "time", "value": 300}}],
    }
    plan = {
        "name": "July block",
        "start_date": "2026-07-01",
        "end_date": "2026-07-14",
        "entries": [{"entry_id": "run-1", "date": "2026-07-10", "workout": inline}],
    }
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_calendar_range",
        return_value=[{"date": "2026-07-10", "workoutId": 10, "workoutScheduleId": 99}],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_workout",
        return_value={
            "workoutId": 10,
            "workoutName": "Easy Run",
            "sportType": {"sportTypeKey": "running"},
            "workoutSegments": [
                {
                    "segmentOrder": 1,
                    "sportType": {"sportTypeKey": "running"},
                    "workoutSteps": [
                        {
                            "type": "ExecutableStepDTO",
                            "stepOrder": 1,
                            "stepType": {"stepTypeKey": "interval"},
                            "endCondition": {"conditionTypeKey": "time"},
                            "endConditionValue": 300,
                            "targetType": {"workoutTargetTypeKey": "no.target"},
                        }
                    ],
                }
            ],
        },
    )
    create = mocker.patch("garmin_cli.mcp_tools.training_plan.create_workout")
    schedule = mocker.patch("garmin_cli.mcp_tools.training_plan.schedule_workout")
    server = create_mcp_server(_config())

    result = _call(server, "training_plan_apply", {"plan": plan})

    assert result["complete"] is True, result
    assert result["outcome"] == "no_op"
    assert result["operations"] == [
        {
            "entry_id": "run-1",
            "action": "keep",
            "state": "no_op",
            "date": "2026-07-10",
            "workout_id": 10,
            "workout_schedule_id": 99,
        }
    ]
    create.assert_not_called()
    schedule.assert_not_called()


def test_reschedule_existing_destination_removes_source(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_calendar_range",
        side_effect=[
            [{"date": "2026-07-05", "workoutId": 10, "workoutScheduleId": 50}],
            [{"date": "2026-07-10", "workoutId": 10, "workoutScheduleId": 99}],
        ],
    )
    schedule = mocker.patch("garmin_cli.mcp_tools.training_plan.schedule_workout")
    unschedule = mocker.patch("garmin_cli.mcp_tools.training_plan.unschedule_workout")
    server = create_mcp_server(_config())

    result = _call(
        server,
        "training_plan_reschedule",
        {
            "schedule_id": 50,
            "expected_date": "2026-07-05",
            "new_date": "2026-07-10",
        },
    )

    assert result["outcome"] == "complete"
    schedule.assert_not_called()
    unschedule.assert_called_once_with(50)


def test_reschedule_cleans_unverified_destination(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_calendar_range",
        side_effect=[
            [{"date": "2026-07-05", "workoutId": 10, "workoutScheduleId": 50}],
            [],
            [],
        ],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.schedule_workout",
        return_value={"workoutScheduleId": 99},
    )
    unschedule = mocker.patch("garmin_cli.mcp_tools.training_plan.unschedule_workout")
    server = create_mcp_server(_config())

    result = _call(
        server,
        "training_plan_reschedule",
        {
            "schedule_id": 50,
            "expected_date": "2026-07-05",
            "new_date": "2026-07-10",
        },
    )

    assert result["outcome"] == "compensated"
    unschedule.assert_called_once_with(99)


def test_reschedule_keeps_source_when_destination_id_is_unavailable(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.get_calendar_range",
        side_effect=[
            [{"date": "2026-07-05", "workoutId": 10, "workoutScheduleId": 50}],
            [],
            [{"date": "2026-07-10", "workoutId": 10}],
        ],
    )
    mocker.patch("garmin_cli.mcp_tools.training_plan.schedule_workout", return_value={})
    unschedule = mocker.patch("garmin_cli.mcp_tools.training_plan.unschedule_workout")
    server = create_mcp_server(_config())

    result = _call(
        server,
        "training_plan_reschedule",
        {
            "schedule_id": 50,
            "expected_date": "2026-07-05",
            "new_date": "2026-07-10",
        },
    )

    assert result["outcome"] == "unknown"
    assert result["conflicts"] == [{"reason": "destination_schedule_id_unavailable"}]
    unschedule.assert_not_called()
