"""Performance MCP tools (race predictions, endurance/hill score, thresholds, VO2 max, zones)."""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from garmin_cli.config import CliConfig
from garmin_cli.endpoints.metrics import (
    get_endurance_score_range,
    get_hill_score_range,
    get_race_predictions,
)
from garmin_cli.endpoints.performance import (
    get_all_thresholds,
    get_lactate_threshold,
    get_latest_vo2max,
    get_personal_records,
    get_vo2max,
)
from garmin_cli.mcp_tools._shared import (
    _authenticated,
    _envelope,
    _parse_date,
    _parse_date_range,
    _run_tool,
)
from garmin_cli.serializers import (
    select_latest_dated_rows,
    serialize_endurance_score,
    serialize_hill_score,
    serialize_personal_records,
    serialize_race_predictions,
    serialize_thresholds,
    serialize_vo2max,
    serialize_zones,
)
from garmin_cli.services.performance import fetch_vo2max


def register_performance_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register the performance-domain read tools on ``mcp``."""

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_race_predictions() -> dict[str, Any]:
        """Get latest race predictions. Returns race_type, predicted_time_seconds, distance_meters."""
        return _run_tool(config, get_race_predictions, serialize_race_predictions)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_personal_records() -> dict[str, Any]:
        """Get all-time personal records. Returns type_id, label, value, activity_type, date, activity_id, activity_name. Label suffix gives units (_s seconds, _m meters, _w watts); records with an unmapped Garmin type_id have label null with the raw value."""
        return _run_tool(config, get_personal_records, serialize_personal_records)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_endurance_score(start_date: str, end_date: str) -> dict[str, Any]:
        """Get endurance score for a date range (YYYY-MM-DD). Returns date, overall_score, endurance_classification."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_endurance_score_range(start, end), serialize_endurance_score)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_hill_score(start_date: str, end_date: str) -> dict[str, Any]:
        """Get hill score for a date range (YYYY-MM-DD). Returns date, overall_score, endurance_score, strength_score."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_hill_score_range(start, end), serialize_hill_score)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_thresholds() -> dict[str, Any]:
        """Get all available threshold metrics. Returns sport, lt_hr_bpm, lt_pace, ftp_watts, weight_kg."""
        return _run_tool(config, get_all_thresholds, serialize_thresholds)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_vo2max(date: str | None = None) -> dict[str, Any]:
        """Get VO2 max. Pass a date (YYYY-MM-DD) for a specific day, or omit for latest. Returns date, vo2max, sport."""
        target_date = _parse_date(date, "date") if date is not None else None
        return _envelope(
            _authenticated(
                config,
                lambda: fetch_vo2max(
                    target_date,
                    get_vo2max=get_vo2max,
                    get_latest_vo2max=get_latest_vo2max,
                    serialize_vo2max=serialize_vo2max,
                    select_latest_dated_rows=select_latest_dated_rows,
                ),
            )
        )

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_zones() -> dict[str, Any]:
        """Get lactate-threshold-derived zone inputs. Returns sport, lt_hr_bpm, lt_pace."""
        return _run_tool(config, get_lactate_threshold, serialize_zones)
