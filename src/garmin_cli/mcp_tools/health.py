"""Health MCP tools (sleep, HRV, weight, daily summary, steps, etc.)."""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from garmin_cli.config import CliConfig
from garmin_cli.endpoints.health import (
    get_body_battery_range,
    get_daily_summary_range,
    get_hrv,
    get_intensity_minutes_range,
    get_resting_hr_range,
    get_sleep,
    get_spo2_range,
    get_steps_range,
    get_stress_range,
    get_training_readiness_range,
    get_training_status,
    get_weight,
)
from garmin_cli.mcp_tools._shared import _parse_date, _parse_date_range, _run_tool
from garmin_cli.serializers import (
    serialize_body_battery,
    serialize_daily_summary,
    serialize_hrv,
    serialize_intensity_minutes,
    serialize_resting_hr,
    serialize_sleep,
    serialize_spo2,
    serialize_steps,
    serialize_stress,
    serialize_training_readiness,
    serialize_training_status,
    serialize_weight,
)


def register_health_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register the health-domain read tools on ``mcp``."""

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_sleep(start_date: str, end_date: str) -> dict[str, Any]:
        """Get sleep data for a date range (YYYY-MM-DD). Returns date, bedtime/wake_time (local ISO), duration_hours, deep/light/rem/awake minutes, and sleep score."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_sleep(start, end), serialize_sleep)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_hrv(start_date: str, end_date: str) -> dict[str, Any]:
        """Get HRV data for a date range (YYYY-MM-DD). Returns date, weekly_avg, last_night, status."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_hrv(start, end), serialize_hrv)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_weight(start_date: str, end_date: str) -> dict[str, Any]:
        """Get weight data for a date range (YYYY-MM-DD). Returns date, weight_kg, bmi, body_fat_pct."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_weight(start, end), serialize_weight)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_daily_summary(start_date: str, end_date: str) -> dict[str, Any]:
        """Get daily summary data for a date range (YYYY-MM-DD). Returns date, total_steps, distance_km, calories, floors, intensity minutes, and resting heart rate. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_daily_summary_range(start, end), serialize_daily_summary)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_steps(start_date: str, end_date: str) -> dict[str, Any]:
        """Get steps data for a date range (YYYY-MM-DD). Returns date, total_steps, total_distance, step_goal."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_steps_range(start, end), serialize_steps)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_intensity_minutes(start_date: str, end_date: str) -> dict[str, Any]:
        """Get intensity minutes for a date range (YYYY-MM-DD). Returns date, moderate_value, vigorous_value, weekly_goal."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_intensity_minutes_range(start, end), serialize_intensity_minutes)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_body_battery(start_date: str, end_date: str) -> dict[str, Any]:
        """Get body battery for a date range (YYYY-MM-DD). Returns date, start_level, end_level, max_level (intraday peak). Fetched in a single ranged call."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_body_battery_range(start, end), serialize_body_battery)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_stress(start_date: str, end_date: str) -> dict[str, Any]:
        """Get stress data for a date range (YYYY-MM-DD). Returns date, avg_stress, max_stress. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_stress_range(start, end), serialize_stress)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_spo2(start_date: str, end_date: str) -> dict[str, Any]:
        """Get SpO2 data for a date range (YYYY-MM-DD). Returns date, avg_spo2, lowest_spo2. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_spo2_range(start, end), serialize_spo2)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_resting_hr(start_date: str, end_date: str) -> dict[str, Any]:
        """Get resting heart rate for a date range (YYYY-MM-DD). Returns date, resting_hr. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_resting_hr_range(start, end), serialize_resting_hr)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_readiness(start_date: str, end_date: str) -> dict[str, Any]:
        """Get training readiness for a date range (YYYY-MM-DD). Returns date, score, level. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_training_readiness_range(start, end), serialize_training_readiness)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def health_training_status(date: str) -> dict[str, Any]:
        """Get training status and load for a single date (YYYY-MM-DD). Returns date, training_status, acute_load (7-day), chronic_load, acwr (acute:chronic workload ratio) + acwr_status, load_tunnel_min/max (productive chronic-load band), monthly load-focus buckets (aerobic_low/aerobic_high/anaerobic) with their target min/max ranges, and load_balance_status."""
        parsed = _parse_date(date, "date")
        return _run_tool(config, lambda: get_training_status(parsed), serialize_training_status)
