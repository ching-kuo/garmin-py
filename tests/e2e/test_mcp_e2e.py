"""E2E tests for MCP tools against the live Garmin Connect API."""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.config import CliConfig
from garmin_cli.mcp_server import create_mcp_server
from mcp.server.mcpserver.exceptions import ToolError
from tests.e2e.conftest import assert_row_has_keys


def _call_tool_json(
    mcp_server: Any,
    rate_limiter: Any,
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    extra_delay: float = 0.0,
) -> dict[str, Any]:
    rate_limiter.wait(extra_delay)
    try:
        result = asyncio.run(mcp_server.call_tool(tool_name, args or {}))
    finally:
        rate_limiter.mark_complete()
    content_list = result[0] if isinstance(result, tuple) else result
    return json.loads(content_list[0].text)


def assert_mcp_envelope_ok(parsed: dict[str, Any]) -> None:
    assert isinstance(parsed, dict), "MCP tool response is not a dict"
    assert "count" in parsed, "Missing 'count' key in MCP response"
    assert "rows" in parsed, "Missing 'rows' key in MCP response"
    assert isinstance(parsed["count"], int), "count is not an int"
    assert isinstance(parsed["rows"], list), "rows is not a list"
    assert parsed["count"] == len(parsed["rows"]), (
        f"count mismatch: count={parsed['count']}, len(rows)={len(parsed['rows'])}"
    )


@pytest.fixture(scope="module")
def mcp_server_live(garth_session):
    config = CliConfig(garth_home=garth_session)
    return create_mcp_server(config)


@pytest.fixture(scope="module")
def single_day_range() -> dict[str, str]:
    today = date.today()
    return {"start_date": today.isoformat(), "end_date": today.isoformat()}


@pytest.fixture(scope="module")
def recent_range() -> dict[str, str]:
    end = date.today()
    start = end - timedelta(days=6)
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


@pytest.mark.e2e
def test_health_daily_summary_mcp(mcp_server_live, rate_limiter, single_day_range):
    parsed = _call_tool_json(mcp_server_live, rate_limiter, "health_daily_summary", single_day_range)
    assert_mcp_envelope_ok(parsed)
    if parsed["rows"]:
        assert_row_has_keys(
            parsed["rows"][0],
            [
                "date",
                "total_steps",
                "distance_km",
                "active_kilocalories",
                "floors_ascended",
                "floors_descended",
                "moderate_intensity_minutes",
                "vigorous_intensity_minutes",
                "resting_heart_rate",
            ],
        )


@pytest.mark.e2e
def test_health_steps_mcp(mcp_server_live, rate_limiter, recent_range):
    parsed = _call_tool_json(mcp_server_live, rate_limiter, "health_steps", recent_range)
    assert_mcp_envelope_ok(parsed)
    if parsed["rows"]:
        assert_row_has_keys(parsed["rows"][0], ["date", "total_steps", "total_distance", "step_goal"])


@pytest.mark.e2e
def test_health_intensity_minutes_mcp(mcp_server_live, rate_limiter, recent_range):
    parsed = _call_tool_json(mcp_server_live, rate_limiter, "health_intensity_minutes", recent_range)
    assert_mcp_envelope_ok(parsed)
    if parsed["rows"]:
        assert_row_has_keys(parsed["rows"][0], ["date", "moderate_value", "vigorous_value", "weekly_goal"])


@pytest.mark.e2e
def test_performance_race_predictions_mcp(mcp_server_live, rate_limiter):
    try:
        parsed = _call_tool_json(mcp_server_live, rate_limiter, "performance_race_predictions", {})
    except ToolError as exc:
        assert "Not found" in str(exc)
    else:
        assert_mcp_envelope_ok(parsed)
        if parsed["rows"]:
            assert_row_has_keys(parsed["rows"][0], ["race_type", "predicted_time_seconds", "distance_meters"])


@pytest.mark.e2e
def test_performance_endurance_score_mcp(mcp_server_live, rate_limiter, single_day_range):
    parsed = _call_tool_json(mcp_server_live, rate_limiter, "performance_endurance_score", single_day_range)
    assert_mcp_envelope_ok(parsed)
    if parsed["rows"]:
        assert_row_has_keys(parsed["rows"][0], ["date", "overall_score", "endurance_classification"])


@pytest.mark.e2e
def test_performance_hill_score_mcp(mcp_server_live, rate_limiter, single_day_range):
    parsed = _call_tool_json(mcp_server_live, rate_limiter, "performance_hill_score", single_day_range)
    assert_mcp_envelope_ok(parsed)
    if parsed["rows"]:
        assert_row_has_keys(parsed["rows"][0], ["date", "overall_score", "endurance_score", "strength_score"])


@pytest.mark.e2e
def test_device_list_mcp(mcp_server_live, rate_limiter):
    parsed = _call_tool_json(mcp_server_live, rate_limiter, "device_list", {})
    assert_mcp_envelope_ok(parsed)
    if parsed["rows"]:
        assert_row_has_keys(parsed["rows"][0], ["device_id", "display_name", "device_type", "last_sync_time"])


@pytest.fixture(scope="module")
def first_activity_id(mcp_server_live, rate_limiter):
    parsed = _call_tool_json(
        mcp_server_live, rate_limiter, "activity_list", {"limit": 1},
    )
    rows = parsed.get("rows") or []
    if not rows:
        return None
    return rows[0].get("id")


@pytest.mark.e2e
def test_activity_get_detail_mcp_manifest(mcp_server_live, rate_limiter, first_activity_id):
    """activity_get(detail=True) returns union schema and (when present)
    a well-formed unavailable[] manifest."""
    if first_activity_id is None:
        pytest.skip("No activities found")
    parsed = _call_tool_json(
        mcp_server_live, rate_limiter,
        "activity_get",
        {"activity_id": int(first_activity_id), "detail": True},
    )
    assert_mcp_envelope_ok(parsed)
    if not parsed["rows"]:
        pytest.skip("No detail row returned")

    row = parsed["rows"][0]
    assert_row_has_keys(
        row,
        [
            "norm_power_w", "intensity_factor", "tss",
            "avg_ground_contact_time", "avg_vertical_oscillation",
            "swolf", "total_strokes",
            "aerobic_training_effect", "anaerobic_training_effect",
        ],
    )

    type_key = (row.get("type") or "").lower()
    is_multisport = "multi" in type_key
    if not is_multisport:
        assert "unavailable" in parsed, "Detail envelope is missing the unavailable[] manifest"
    if "unavailable" in parsed:
        manifest = parsed["unavailable"]
        assert isinstance(manifest, list)
        for entry in manifest:
            assert_row_has_keys(entry, ["field", "reason"])
            assert entry["reason"] in {
                "not_applicable_to_sport", "absent_in_response",
            }
        if not is_multisport:
            assert any(
                e["reason"] == "not_applicable_to_sport" for e in manifest
            ), "Expected at least one not_applicable_to_sport entry for a sport-specific activity"


@pytest.mark.e2e
def test_activity_laps_mcp(mcp_server_live, rate_limiter, first_activity_id):
    if first_activity_id is None:
        pytest.skip("No activities found")
    parsed = _call_tool_json(
        mcp_server_live, rate_limiter,
        "activity_laps",
        {"activity_id": int(first_activity_id)},
    )
    assert_mcp_envelope_ok(parsed)
    if parsed["rows"]:
        assert_row_has_keys(
            parsed["rows"][0],
            ["lap_index", "duration_min", "distance_km"],
        )


@pytest.mark.e2e
def test_activity_hr_zones_mcp(mcp_server_live, rate_limiter, first_activity_id):
    if first_activity_id is None:
        pytest.skip("No activities found")
    parsed = _call_tool_json(
        mcp_server_live, rate_limiter,
        "activity_hr_zones",
        {"activity_id": int(first_activity_id)},
    )
    assert_mcp_envelope_ok(parsed)
    if parsed["rows"]:
        assert_row_has_keys(
            parsed["rows"][0],
            ["zone", "zone_low_bpm", "zone_high_bpm", "minutes_in_zone"],
        )


@pytest.mark.e2e
def test_activity_metrics_describe_mcp(mcp_server_live, rate_limiter, first_activity_id):
    if first_activity_id is None:
        pytest.skip("No activities found")
    parsed = _call_tool_json(
        mcp_server_live, rate_limiter,
        "activity_metrics_describe",
        {"activity_id": int(first_activity_id)},
    )
    assert_mcp_envelope_ok(parsed)
    if parsed["rows"]:
        first = parsed["rows"][0]
        assert_row_has_keys(first, ["key", "unit", "metricsIndex"])
        # A descriptor row with key=None means the wire field name drifted
        # (e.g. metricDescriptorKey vs key) and rows are silently empty.
        assert first["key"] is not None, (
            "metric descriptor key is None; serializer may be reading the wrong wire field"
        )


@pytest.mark.e2e
def test_activity_laps_mcp_multisport_fan_out(mcp_server_live, rate_limiter):
    """activity_laps fans out across multisport child legs and stamps leg_index."""
    parsed = _call_tool_json(
        mcp_server_live, rate_limiter,
        "activity_list",
        {"limit": 50, "activity_type": "multi_sport"},
    )
    rows = parsed.get("rows") or []
    if not rows:
        pytest.skip("No multisport activities found in account")

    ms_id = int(rows[0]["id"])
    parsed = _call_tool_json(
        mcp_server_live, rate_limiter, "activity_laps", {"activity_id": ms_id},
    )
    assert_mcp_envelope_ok(parsed)
    if not parsed["rows"]:
        pytest.skip("Multisport parent has no lap rows from any leg")

    assert all(
        isinstance(row.get("leg_index"), int) for row in parsed["rows"]
    ), "Multisport laps must stamp integer leg_index on every row"
    leg_indices = {row["leg_index"] for row in parsed["rows"]}
    assert min(leg_indices) == 0, "leg_index is 0-based"
    assert len(leg_indices) >= 2, (
        "Expected fan-out across >=2 multisport child legs"
    )
