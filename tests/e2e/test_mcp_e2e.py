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
