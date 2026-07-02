"""Workout MCP tool tests (moved from test_mcp_server.py; assertions unchanged)."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


class TestWorkoutTools:

    def test_workout_list(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.workouts.list_workouts", return_value=[{"workoutId": 1, "workoutName": "Easy Run", "sportType": {"sportTypeKey": "running"}, "estimatedDurationInSecs": 1800}])
        server = create_mcp_server(_config())
        result = _call(server, "workout_list", {"limit": 10})
        assert result["count"] == 1
        assert result["rows"][0]["name"] == "Easy Run"

    def test_workout_get(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.workouts.get_workout", return_value={"workoutId": 1, "workoutName": "Easy Run", "sportType": {"sportTypeKey": "running"}, "estimatedDurationInSecs": 1800, "workoutSegments": []})
        server = create_mcp_server(_config())
        result = _call(server, "workout_get", {"workout_id": 1})
        assert result["count"] == 1

    def test_workout_calendar(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.workouts.get_calendar_range", return_value=[{"date": "2026-01-01", "workoutId": 1, "title": "Easy Run", "workoutTypeKey": "running", "durationInSeconds": 1800}])
        server = create_mcp_server(_config())
        result = _call(server, "workout_calendar", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
        assert result["count"] == 1


_VALID_WORKOUT = {
    "name": "Easy Run",
    "sport": "running",
    "steps": [
        {
            "type": "interval",
            "duration": {"type": "time", "value": 1800},
            "target": {"type": "no.target"},
        }
    ],
}


class TestMcpWorkoutCreate:
    """workout_create: validate / build / dry_run / live / errors / logging."""

    def test_live_create_happy_path(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        create = mocker.patch(
            "garmin_cli.mcp_tools.workouts.create_workout",
            return_value={"workoutId": 12345, "workoutName": "Easy Run"},
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "workout_create", {"workout": dict(_VALID_WORKOUT)})

        assert result["count"] == 1
        row = result["rows"][0]
        assert row == {"ok": True, "action": "created", "workout_id": 12345}
        create.assert_called_once()
        log.assert_called_once()
        event = log.call_args.args[0]
        assert event.tool == "workout_create"
        assert event.outcome == "success"
        assert event.dry_run is False
        assert event.workout_id == 12345
        assert event.name_len == len("Easy Run")

    def test_dry_run_skips_garmin_and_auth(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        create = mocker.patch("garmin_cli.mcp_tools.workouts.create_workout")
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_create",
            {"workout": dict(_VALID_WORKOUT), "dry_run": True},
        )

        assert result["count"] == 1
        row = result["rows"][0]
        assert row["ok"] is True
        assert row["dry_run"] is True
        assert row["validation_report"] == {"ok": True}
        assert "wire_payload" in row
        assert row["wire_payload"]["workoutName"] == "Easy Run"
        # The load-bearing safety contract: dry-run never touches Garmin or auth.
        auth.assert_not_called()
        create.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "dry-run"
        assert event.dry_run is True

    def test_validation_error_returns_envelope(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        create = mocker.patch("garmin_cli.mcp_tools.workouts.create_workout")
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        bad = {"name": "x", "sport": "running", "steps": []}  # empty steps
        result = _call(server, "workout_create", {"workout": bad})

        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        assert isinstance(row["errors"], list)
        assert any("steps" in e for e in row["errors"])
        auth.assert_not_called()
        create.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "failed-validation"
        assert event.errors_count == len(row["errors"])

    def test_validation_warmupp_typo(self, mocker: Any) -> None:
        """AE5: a step with type='warmupp' is rejected by the validator."""
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.workouts.create_workout")
        mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        bad = {
            "name": "Easy Run",
            "sport": "running",
            "steps": [
                {
                    "type": "warmupp",
                    "duration": {"type": "time", "value": 600},
                    "target": {"type": "no.target"},
                }
            ],
        }
        result = _call(server, "workout_create", {"workout": bad})
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        assert any("warmupp" in e for e in row["errors"])

    def test_dry_run_with_validation_errors(self, mocker: Any) -> None:
        """dry_run=True does not bypass validation."""
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        create = mocker.patch("garmin_cli.mcp_tools.workouts.create_workout")
        mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_create",
            {"workout": {"name": "x", "sport": "running", "steps": []}, "dry_run": True},
        )
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        create.assert_not_called()

    def test_auth_missing_on_live(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "workout_create", {"workout": dict(_VALID_WORKOUT)})

        event = log.call_args.args[0]
        assert event.outcome == "failed-auth"

    def test_dry_run_skips_auth_failure(self, mocker: Any) -> None:
        """dry_run=True does not call ensure_authenticated even when it would fail."""
        auth = mocker.patch(
            "garmin_cli.mcp_tools.workouts.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_create",
            {"workout": dict(_VALID_WORKOUT), "dry_run": True},
        )
        assert result["rows"][0]["ok"] is True
        auth.assert_not_called()

    def test_upstream_failure(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.create_workout",
            side_effect=GarminCliError(error="Internal server error.", error_code="SERVER_ERROR"),
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Internal server error"):
            _call(server, "workout_create", {"workout": dict(_VALID_WORKOUT)})

        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"


def _tool_annotations(server: Any, tool_name: str) -> Any:
    tools = asyncio.run(server.list_tools())
    for t in tools:
        if t.name == tool_name:
            return t.annotations
    raise AssertionError(f"tool {tool_name!r} not registered")


class TestMcpWorkoutSchedule:

    def test_happy_path(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.schedule_workout",
            return_value={"workoutScheduleId": 9988, "calendarDate": "2026-06-01"},
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_schedule",
            {"workout_id": 12345, "date": "2026-06-01"},
        )

        row = result["rows"][0]
        assert row == {
            "ok": True,
            "action": "scheduled",
            "workout_id": 12345,
            "workout_schedule_id": 9988,
            "date": "2026-06-01",
        }
        event = log.call_args.args[0]
        assert event.tool == "workout_schedule"
        assert event.outcome == "success"
        assert event.workout_id == 12345

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "workout_schedule")
        assert ann is not None
        assert ann.destructive_hint is True

    def test_bad_date_format(self, mocker: Any) -> None:
        schedule = mocker.patch("garmin_cli.mcp_tools.workouts.schedule_workout")
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="Invalid date format"):
            _call(server, "workout_schedule", {"workout_id": 1, "date": "not-a-date"})
        schedule.assert_not_called()

    def test_invalid_workout_id(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "workout_schedule", {"workout_id": 0, "date": "2026-01-01"})

    def test_auth_missing(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "workout_schedule", {"workout_id": 1, "date": "2026-06-01"})

        event = log.call_args.args[0]
        assert event.outcome == "failed-auth"

    def test_upstream_not_found(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.schedule_workout",
            side_effect=GarminCliError(error="Not found.", error_code="NOT_FOUND"),
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Not found"):
            _call(server, "workout_schedule", {"workout_id": 99, "date": "2026-06-01"})

        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"


_EXISTING_WORKOUT = {
    "workoutId": 42,
    "workoutName": "Old Name",
    "ownerId": 99,
    "createdDate": "2025-12-01T00:00:00",
    "atpPlanId": 7,
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSegments": [
        {
            "segmentOrder": 1,
            "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
            "workoutSteps": [],
        }
    ],
}


class TestMcpWorkoutUpdate:

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "workout_update")
        assert ann is not None
        assert ann.destructive_hint is True

    def test_dry_run_reads_but_does_not_write(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        get = mocker.patch(
            "garmin_cli.mcp_tools.workouts.get_workout",
            return_value=dict(_EXISTING_WORKOUT),
        )
        update = mocker.patch("garmin_cli.mcp_tools.workouts.update_workout")
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_update",
            {"workout_id": 42, "workout": {"name": "New Name"}, "dry_run": True},
        )

        row = result["rows"][0]
        assert row["ok"] is True
        assert row["dry_run"] is True
        assert "wire_payload" in row
        assert row["wire_payload"]["workoutName"] == "New Name"
        # Lineage preserved by merge_workout_payload deepcopy.
        assert row["wire_payload"]["workoutId"] == 42
        assert row["wire_payload"]["ownerId"] == 99
        assert row["wire_payload"]["atpPlanId"] == 7
        get.assert_called_once_with(42)
        update.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "dry-run"
        assert event.dry_run is True

    def test_live_update_calls_both_get_and_update(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.get_workout",
            return_value=dict(_EXISTING_WORKOUT),
        )
        update = mocker.patch("garmin_cli.mcp_tools.workouts.update_workout")
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_update",
            {"workout_id": 42, "workout": {"name": "New Name"}},
        )

        row = result["rows"][0]
        assert row == {"ok": True, "action": "updated", "workout_id": 42}
        update.assert_called_once()
        called_workout_id, called_payload = update.call_args.args
        assert called_workout_id == 42
        assert called_payload["workoutName"] == "New Name"
        # The merged payload preserves the existing workoutId and atpPlanId.
        assert called_payload["workoutId"] == 42
        assert called_payload["atpPlanId"] == 7
        event = log.call_args.args[0]
        assert event.outcome == "success"

    def test_merge_warnings_in_dry_run(self, mocker: Any) -> None:
        """When user_input contains read-only fields, merge_workout_payload
        emits a warning that surfaces in the dry-run validation_report."""
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.get_workout",
            return_value=dict(_EXISTING_WORKOUT),
        )
        mocker.patch("garmin_cli.mcp_tools.workouts.update_workout")
        mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "workout_update",
            {
                "workout_id": 42,
                "workout": {"name": "New Name", "workoutId": 999},
                "dry_run": True,
            },
        )
        warnings = result["rows"][0]["validation_report"]["warnings"]
        assert any("workoutId" in w for w in warnings)

    def test_validation_error_blocks_garmin_calls(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        get = mocker.patch("garmin_cli.mcp_tools.workouts.get_workout")
        update = mocker.patch("garmin_cli.mcp_tools.workouts.update_workout")
        mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        # Empty string name -- fails partial validator.
        result = _call(
            server,
            "workout_update",
            {"workout_id": 42, "workout": {"name": ""}},
        )
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        auth.assert_not_called()
        get.assert_not_called()
        update.assert_not_called()

    def test_auth_missing(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        get = mocker.patch("garmin_cli.mcp_tools.workouts.get_workout")
        update = mocker.patch("garmin_cli.mcp_tools.workouts.update_workout")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "workout_update", {"workout_id": 42, "workout": {"name": "x"}})

        get.assert_not_called()
        update.assert_not_called()

    def test_get_workout_404(self, mocker: Any) -> None:
        """When the workout to update doesn't exist, fail before writing."""
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.get_workout",
            side_effect=GarminCliError(error="Not found.", error_code="NOT_FOUND"),
        )
        update = mocker.patch("garmin_cli.mcp_tools.workouts.update_workout")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Not found"):
            _call(server, "workout_update", {"workout_id": 42, "workout": {"name": "x"}})

        update.assert_not_called()

    def test_update_workout_upstream_failure(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.get_workout",
            return_value=dict(_EXISTING_WORKOUT),
        )
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.update_workout",
            side_effect=GarminCliError(error="Internal server error.", error_code="SERVER_ERROR"),
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Internal server error"):
            _call(server, "workout_update", {"workout_id": 42, "workout": {"name": "x"}})

        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"

    def test_update_workout_auth_failed_during_write(self, mocker: Any) -> None:
        """AUTH_FAILED during update_workout should log as 'failed-auth', not 'failed-upstream'."""
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.get_workout",
            return_value=dict(_EXISTING_WORKOUT),
        )
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.update_workout",
            side_effect=GarminCliError(error="Token expired.", error_code="AUTH_FAILED"),
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError):
            _call(server, "workout_update", {"workout_id": 42, "workout": {"name": "x"}})

        event = log.call_args.args[0]
        assert event.outcome == "failed-auth"

    def test_invalid_workout_id(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "workout_update", {"workout_id": 0, "workout": {"name": "x"}})


class TestMcpWorkoutDelete:

    def test_happy_path(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        delete = mocker.patch("garmin_cli.mcp_tools.workouts.delete_workout")
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "workout_delete", {"workout_id": 12345})
        row = result["rows"][0]
        assert row == {"ok": True, "action": "deleted", "workout_id": 12345}
        delete.assert_called_once_with(12345)
        event = log.call_args.args[0]
        assert event.tool == "workout_delete"
        assert event.outcome == "success"
        assert event.workout_id == 12345

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "workout_delete")
        assert ann is not None
        assert ann.destructive_hint is True

    def test_invalid_workout_id(self, mocker: Any) -> None:
        delete = mocker.patch("garmin_cli.mcp_tools.workouts.delete_workout")
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "workout_delete", {"workout_id": -1})
        delete.assert_not_called()

    def test_auth_missing(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        delete = mocker.patch("garmin_cli.mcp_tools.workouts.delete_workout")
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "workout_delete", {"workout_id": 1})

        delete.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "failed-auth"

    @pytest.mark.parametrize("error_code", ["NOT_FOUND", "AUTH_FAILED"])
    def test_upstream_not_found_or_auth_failed(
        self, mocker: Any, error_code: str
    ) -> None:
        """AE4: Garmin returns NOT_FOUND or AUTH_FAILED for inaccessible IDs."""
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.delete_workout",
            side_effect=GarminCliError(error="Inaccessible.", error_code=error_code),
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError):
            _call(server, "workout_delete", {"workout_id": 999999999})

        event = log.call_args.args[0]
        expected_outcome = "failed-auth" if error_code == "AUTH_FAILED" else "failed-upstream"
        assert event.outcome == expected_outcome


class TestMcpWorkoutUnschedule:

    def test_happy_path(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        unschedule = mocker.patch("garmin_cli.mcp_tools.workouts.unschedule_workout")
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "workout_unschedule", {"schedule_id": 555})
        row = result["rows"][0]
        assert row == {"ok": True, "action": "unscheduled", "schedule_id": 555}
        unschedule.assert_called_once_with(555)
        event = log.call_args.args[0]
        assert event.tool == "workout_unschedule"
        assert event.outcome == "success"
        assert event.workout_id == 555

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "workout_unschedule")
        assert ann is not None
        assert ann.destructive_hint is True

    def test_invalid_schedule_id(self, mocker: Any) -> None:
        unschedule = mocker.patch("garmin_cli.mcp_tools.workouts.unschedule_workout")
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "workout_unschedule", {"schedule_id": 0})
        unschedule.assert_not_called()

    def test_auth_missing(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "workout_unschedule", {"schedule_id": 555})

        event = log.call_args.args[0]
        assert event.outcome == "failed-auth"

    def test_upstream_not_found(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.workouts.unschedule_workout",
            side_effect=GarminCliError(error="Not found.", error_code="NOT_FOUND"),
        )
        log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Not found"):
            _call(server, "workout_unschedule", {"schedule_id": 999})

        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"
