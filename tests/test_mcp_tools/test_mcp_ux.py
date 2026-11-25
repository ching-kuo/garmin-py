"""MCP surface for LLM callers: typed inputs, slim tools/list, range defaults, read-only mode, audit log."""
from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, get_args

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli.mcp_server import READ_ONLY_GUIDANCE, WRITE_TOOLS, create_mcp_server  # noqa: E402
from garmin_cli.mcp_tools import _inputs  # noqa: E402
from garmin_cli.services.training_plan import _ENTRY_FIELDS, _PLAN_FIELDS, _REMOVAL_FIELDS  # noqa: E402
from garmin_cli.workout_schema import (  # noqa: E402
    _DURATION_FIELDS,
    _REPEAT_STEP_FIELDS,
    _STEP_FIELDS,
    READ_ONLY_FIELDS,
    SPORT_TYPES,
    STEP_TYPES,
    TARGET_TYPES,
    WORKOUT_FIELDS,
)
from tests.test_mcp_tools.support import _call, _config  # noqa: E402

# tools/list JSON size of these tools at 0cef65c, before the Envelope output
# schema was dropped; the typed plan/workout inputs are paid for out of it.
# Tools added later are outside this budget; a rename fails the set check.
_TOOLS_LIST_CHARS_BEFORE = 66_094
_BASELINE_TOOLS = frozenset({
    "health_sleep", "health_hrv", "health_weight", "health_daily_summary", "health_steps",
    "health_intensity_minutes", "health_body_battery", "health_stress", "health_spo2",
    "health_resting_hr", "health_readiness", "health_training_status",
    "activity_list", "activity_get", "activity_weather", "activity_laps", "activity_hr_zones",
    "activity_metrics_describe", "activity_detail_metrics", "activity_download", "activity_upload",
    "activity_delete", "activity_rename", "activity_set_type",
    "workout_list", "workout_get", "workout_calendar", "workout_create", "workout_schedule",
    "workout_update", "workout_delete", "workout_unschedule",
    "coach_snapshot", "training_plan_reconcile", "training_plan_preview", "training_plan_apply",
    "training_plan_reschedule",
    "performance_race_predictions", "performance_personal_records", "performance_endurance_score",
    "performance_hill_score", "performance_thresholds", "performance_vo2max", "performance_zones",
    "performance_ftp_history", "performance_acclimation", "performance_cycling_ability",
    "performance_power_curve", "performance_fastest_splits",
    "device_list", "login_status", "server_doctor", "submit_mfa_code", "report_snapshot",
})

_WORKOUT = {
    "name": "Intervals",
    "sport": "running",
    "steps": [
        {"type": "warmup", "duration": {"type": "time", "value": 600}, "target": {"type": "open"}},
        {
            "type": "repeat",
            "count": 4,
            "steps": [
                {"type": "interval", "duration": {"type": "distance", "value": 400.5},
                 "target": {"type": "power.zone", "zone": 6}},
                {"type": "recovery", "duration": {"type": "time", "value": 90}, "target": None},
            ],
        },
    ],
}


def _tools(server: Any) -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def test_tools_list_shrinks_by_at_least_thirty_percent() -> None:
    tools = asyncio.run(create_mcp_server(_config()).list_tools())
    assert len(_BASELINE_TOOLS) == 54
    assert _BASELINE_TOOLS <= {t.name for t in tools}
    size = sum(
        len(json.dumps(t.model_dump(mode="json", by_alias=True, exclude_none=True)))
        for t in tools
        if t.name in _BASELINE_TOOLS
    )
    assert size <= _TOOLS_LIST_CHARS_BEFORE * 0.7, size
    assert '"title"' not in json.dumps([t.input_schema for t in tools])
    assert '"title"' not in json.dumps([t.output_schema for t in tools])


def test_inline_plan_workout_publishes_the_full_workout_schema() -> None:
    schema = _tools(create_mcp_server(_config()))["training_plan_apply"].input_schema
    inline = schema["$defs"]["PlanEntry"]["properties"]["workout"]
    workout = schema["$defs"][inline["$ref"].rsplit("/", 1)[1]]
    assert workout["required"] == ["name", "sport", "steps"]
    assert workout["additionalProperties"] is False


@pytest.mark.parametrize(
    ("typed", "fields"),
    [
        (_inputs.WorkoutInput, WORKOUT_FIELDS),
        (_inputs.WorkoutUpdate, WORKOUT_FIELDS | READ_ONLY_FIELDS),
        (_inputs.Duration, _DURATION_FIELDS),
        (_inputs.Step, _STEP_FIELDS | _REPEAT_STEP_FIELDS),
        (_inputs.TrainingPlan, _PLAN_FIELDS),
        (_inputs.PlanEntry, _ENTRY_FIELDS),
        (_inputs.PlanRemoval, _REMOVAL_FIELDS),
    ],
)
def test_input_keys_match_the_validator_field_tables(typed: Any, fields: frozenset[str]) -> None:
    assert set(typed.__annotations__) - {"__pydantic_config__"} == set(fields)


def test_generic_tools_publish_a_plain_object_output_schema() -> None:
    tools = _tools(create_mcp_server(_config()))
    for name in ("health_sleep", "activity_list", "workout_create", "device_list", "server_doctor"):
        assert tools[name].output_schema == {"additionalProperties": True, "type": "object"}
    assert set(tools["activity_get"].output_schema["required"]) == {"count", "rows"}
    for key in ("children", "unavailable"):
        assert {"type": "null"} in tools["activity_get"].output_schema["properties"][key]["anyOf"]


def test_structured_inputs_publish_nested_schemas() -> None:
    tools = _tools(create_mcp_server(_config()))
    create = tools["workout_create"].input_schema
    assert create["$defs"]["Step"]["properties"]["type"]["enum"] == list(get_args(_inputs.StepType))
    assert "power.zone" in create["$defs"]["Target"]["properties"]["type"]["enum"]
    update_props = tools["workout_update"].input_schema["$defs"]["WorkoutUpdate"]["properties"]
    assert "workoutId" in update_props
    plan = tools["training_plan_apply"].input_schema["$defs"]
    assert plan["TrainingPlan"]["required"] == ["name", "start_date", "end_date", "entries"]
    assert "expected_source_date" in plan["PlanEntry"]["properties"]
    assert plan["PlanRemoval"]["required"] == ["schedule_id", "expected_date"]


def test_input_enums_match_the_validator_tables() -> None:
    assert set(get_args(_inputs.Sport)) == set(SPORT_TYPES)
    assert set(get_args(_inputs.StepType)) == set(STEP_TYPES)
    assert set(get_args(_inputs.TargetType)) == set(TARGET_TYPES)


def test_valid_workout_passes_the_schema_unchanged(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
    build = mocker.patch("garmin_cli.mcp_tools.workouts.build_garmin_payload", return_value={})
    _call(create_mcp_server(_config()), "workout_create", {"workout": _WORKOUT, "dry_run": True})
    assert build.call_args.args[0] == _WORKOUT
    assert build.call_args.args[0]["steps"][0]["duration"]["value"] == 600  # still an int


def test_update_tolerates_read_only_garmin_fields(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
    mocker.patch("garmin_cli.mcp_tools.workouts.get_workout", return_value={"workoutId": 7})
    merge = mocker.patch("garmin_cli.mcp_tools.workouts.merge_workout_payload", return_value=({}, []))
    mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
    args = {"workout_id": 7, "workout": {"name": "Renamed", "workoutId": 7, "ownerId": 1}, "dry_run": True}
    result = _call(create_mcp_server(_config()), "workout_update", args)
    assert result["rows"][0]["ok"] is True
    assert merge.call_args.args[1] == {"name": "Renamed", "workoutId": 7, "ownerId": 1}


@pytest.mark.parametrize(
    ("workout", "message"),
    [
        ({**_WORKOUT, "colour": "red"}, "colour"),
        ({**_WORKOUT, "steps": [{"type": "rest", "duration": {"type": "time", "value": "60"}}]}, "value"),
        ({**_WORKOUT, "sport": "rowing"}, "sport"),
    ],
)
def test_invalid_workout_shape_is_rejected_with_the_path(workout: dict[str, Any], message: str) -> None:
    with pytest.raises(ToolError, match=message):
        _call(create_mcp_server(_config()), "workout_create", {"workout": workout})


def test_plan_with_inline_workout_passes_and_bad_shape_names_the_path(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch("garmin_cli.mcp_tools.training_plan.get_calendar_range", return_value=[])
    plan = {
        "name": "Block",
        "start_date": "2026-07-01",
        "end_date": "2026-07-07",
        "entries": [{"entry_id": "a", "date": "2026-07-02", "workout": _WORKOUT}],
    }
    server = create_mcp_server(_config())
    assert _call(server, "training_plan_preview", {"plan": plan})["complete"] is True

    bad = {**plan, "entries": [{"entry_id": "a", "date": "2026-07-02", "workout_id": "10"}]}
    with pytest.raises(ToolError, match=r"plan\.entries\.0\.workout_id"):
        _call(server, "training_plan_preview", {"plan": bad})


def test_literal_enum_params_are_published() -> None:
    tools = _tools(create_mcp_server(_config()))
    assert tools["report_snapshot"].input_schema["properties"]["kind"]["enum"] == ["morning", "evening", "weekly"]
    assert tools["training_plan_reconcile"].input_schema["properties"]["detail"]["enum"] == ["summary", "targets"]
    assert "gpx" in tools["activity_download"].input_schema["properties"]["fmt"]["enum"]


class TestRangeDefaults:
    def _sleep(self, mocker: Any, args: dict[str, Any]) -> Any:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools._shared.today", return_value=date(2026, 7, 10))
        get_sleep = mocker.patch("garmin_cli.mcp_tools.health.get_sleep", return_value=[])
        _call(create_mcp_server(_config()), "health_sleep", args)
        return get_sleep.call_args.args

    def test_days_ends_at_profile_today(self, mocker: Any) -> None:
        assert self._sleep(mocker, {"days": 7}) == (date(2026, 7, 4), date(2026, 7, 10))

    def test_start_date_alone_ends_today(self, mocker: Any) -> None:
        assert self._sleep(mocker, {"start_date": "2026-07-01"}) == (date(2026, 7, 1), date(2026, 7, 10))

    def test_days_with_explicit_end(self, mocker: Any) -> None:
        assert self._sleep(mocker, {"days": 2, "end_date": "2026-06-30"}) == (date(2026, 6, 29), date(2026, 6, 30))

    def test_explicit_range_still_works_on_performance_tools(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        get_ftp = mocker.patch("garmin_cli.mcp_tools.performance.get_ftp_history", return_value=[])
        args = {"start_date": "2026-07-01", "end_date": "2026-07-02", "sport": "running"}
        _call(create_mcp_server(_config()), "performance_ftp_history", args)
        assert get_ftp.call_args.args == (date(2026, 7, 1), date(2026, 7, 2), "running")

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            ({}, "start_date or days"),
            ({"start_date": "2026-07-01", "days": 3}, "not both"),
            ({"days": 91}, "less than or equal to 90"),
            ({"days": 0}, "greater than or equal to 1"),
            ({"days": "7"}, "valid integer"),
            ({"days": True}, "valid integer"),
            ({"days": 90, "end_date": "0001-01-05"}, "before 0001-01-01"),
            ({"start_date": "2026-07-02", "end_date": "2026-07-01"}, "on or before"),
        ],
    )
    def test_conflicts_are_rejected_before_auth(self, mocker: Any, args: dict[str, Any], message: str) -> None:
        auth = mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        with pytest.raises(ToolError, match=message):
            _call(create_mcp_server(_config()), "health_hrv", args)
        auth.assert_not_called()


class TestReadOnlyMode:
    def test_write_tools_are_not_registered(self) -> None:
        tools = _tools(create_mcp_server(_config(), read_only=True))
        assert not set(WRITE_TOOLS) & set(tools)
        assert {"submit_mfa_code", "training_plan_preview", "workout_list", "activity_get"} <= set(tools)

    def test_write_tools_are_exactly_the_destructive_ones_except_mfa(self) -> None:
        tools = _tools(create_mcp_server(_config()))
        destructive = {name for name, tool in tools.items() if tool.annotations.destructive_hint}
        assert destructive - {"submit_mfa_code"} == set(WRITE_TOOLS)

    def test_instructions_and_doctor_report_the_mode(self, mocker: Any) -> None:
        server = create_mcp_server(_config(), read_only=True)
        assert server.instructions is not None and READ_ONLY_GUIDANCE in server.instructions
        assert "destructive_hint" not in server.instructions
        assert "destructive_hint" in create_mcp_server(_config()).instructions
        rows = _call(server, "server_doctor", {"fast": True})["rows"]
        surface = next(row for row in rows if row["name"] == "write_surface")
        assert "read-only" in surface["detail"]
