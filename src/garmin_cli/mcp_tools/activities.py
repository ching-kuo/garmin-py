"""Activity MCP tools (list, get, weather, laps, HR zones, metrics-describe)."""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from garmin_cli.config import CliConfig
from garmin_cli.endpoints.activities import (
    activity_type_key,
    get_activity,
    get_activity_details,
    get_activity_hr_in_timezones,
    get_activity_splits,
    get_activity_typed_splits,
    get_activity_weather,
    get_multisport_children,
    is_multisport_parent,
    list_activities,
)
from garmin_cli.mcp_tools._shared import (
    _authenticated,
    _envelope,
    _parse_date_range,
    _run_tool,
    _validate_limit,
    _validate_positive_id,
)
from garmin_cli.serializers import (
    serialize_activity_detail,
    serialize_activity_hr_zones,
    serialize_activity_laps,
    serialize_activity_summary,
    serialize_activity_weather,
    serialize_capability_manifest,
    serialize_metrics_descriptors,
    serialize_multisport_children,
)
from garmin_cli.services.activities import (
    build_capability_manifest,
    fetch_laps_for_activity,
)


def _validate_start_offset(value: int) -> int:
    if value < 0:
        raise ToolError(f"start offset must be >= 0, got {value}")
    return value


def _fetch_laps_rows_for_activity(activity: dict[str, Any], activity_id: Any) -> list[dict[str, Any]]:
    """Fetch laps; for multisport parents, fan out to children with leg_index.

    Thin wrapper over :func:`garmin_cli.services.activities.fetch_laps_for_activity`
    that binds this module's endpoint/serializer references so test patches on
    ``garmin_cli.mcp_tools.activities.*`` stay effective. The service returns a
    ``(rows, profile)`` pair; the MCP front-end uses only the rows.
    """
    rows, _profile = fetch_laps_for_activity(
        activity,
        activity_id,
        activity_type_key=activity_type_key,
        is_multisport_parent=is_multisport_parent,
        get_multisport_children=get_multisport_children,
        splits_fn=get_activity_splits,
        typed_splits_fn=get_activity_typed_splits,
        serialize_laps=serialize_activity_laps,
    )
    return rows


def register_activity_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register the activity-domain read tools on ``mcp``."""

    @mcp.tool()
    def activity_list(
        limit: int = 20,
        start: int = 0,
        activity_type: str | None = None,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """List recent activities, optionally filtered by date range (YYYY-MM-DD). Returns id, date, name, type, distance_km, duration_min, avg_hr."""
        _validate_limit(limit)
        _validate_start_offset(start)
        parsed_start = None
        parsed_end = None
        if (start_date is None) != (end_date is None):
            raise ToolError("start_date and end_date must be provided together")
        if start_date is not None and end_date is not None:
            parsed_start, parsed_end = _parse_date_range(start_date, end_date)
        return _run_tool(
            config,
            lambda: list_activities(limit, start, activity_type, search, parsed_start, parsed_end),
            serialize_activity_summary,
        )

    @mcp.tool()
    def activity_get(activity_id: int, detail: bool = False) -> dict[str, Any]:
        """Get a single activity by ID. For multisport activities (triathlon etc.), includes child activities with per-sport details. Returns compact activity fields by default, or extended sport-aware metrics including elapsed_time_min (total wall-clock time incl. stops; duration_min is moving time), running dynamics (GCT, vertical oscillation/ratio, stride length), cycling power suite (avg/max/normalized power, TSS, IF) and cadence, swim aggregates (SWOLF, strokes), and training response (aerobic/anaerobic training effect, vO2max, recovery time) when detail=True. When detail=True, the response carries an additional ``unavailable`` array (when non-empty) annotating which registry-known metrics are not applicable to this sport (``not_applicable_to_sport``) or unexpectedly absent (``absent_in_response``)."""
        _validate_positive_id(activity_id, "activity_id")

        def produce() -> dict[str, Any]:
            raw = get_activity(activity_id)
            rows = serialize_activity_detail(raw) if detail else serialize_activity_summary(raw)
            result = _envelope(rows)
            children: list[dict[str, Any]] = []
            if is_multisport_parent(raw):
                fetched = get_multisport_children(raw)
                if fetched:
                    children = fetched
                    result["children"] = serialize_multisport_children(fetched)
            if detail:
                manifest = build_capability_manifest(
                    raw,
                    rows,
                    children,
                    serialize_detail=serialize_activity_detail,
                    serialize_manifest=serialize_capability_manifest,
                )
                if manifest:
                    result["unavailable"] = manifest
            return result

        return _authenticated(config, produce)

    @mcp.tool()
    def activity_weather(activity_id: int) -> dict[str, Any]:
        """Get weather for an activity. Returns temperature, apparent_temp, dew_point, humidity, wind_speed, wind_gust, wind_direction, wind_direction_compass, and condition. Temperature fields are in the Garmin account's display unit (often Fahrenheit). Garmin's activity-weather feed has no precipitation-probability or icon-code field."""
        _validate_positive_id(activity_id, "activity_id")
        return _run_tool(config, lambda: get_activity_weather(activity_id), serialize_activity_weather)

    @mcp.tool()
    def activity_laps(activity_id: int) -> dict[str, Any]:
        """Get lap-by-lap data for an activity. For pool-swim activities returns per-pool-length rows with SWOLF, stroke type, and stroke counts; for run/bike activities returns per-lap rows with start_time_gmt/start_time_local, HR, power and cadence (cycling), and running dynamics. For multisport parents (triathlon etc.), returns each child leg's laps concatenated with a 0-based ``leg_index`` stamped on every row."""
        _validate_positive_id(activity_id, "activity_id")
        return _run_tool(config, lambda: _fetch_laps_rows_for_activity(get_activity(activity_id), activity_id))

    @mcp.tool()
    def activity_hr_zones(activity_id: int) -> dict[str, Any]:
        """Get HR time-in-zone breakdown for an activity. Returns one row per zone: zone, zone_low_bpm, zone_high_bpm, seconds_in_zone, minutes_in_zone."""
        _validate_positive_id(activity_id, "activity_id")
        return _run_tool(config, lambda: get_activity_hr_in_timezones(activity_id), serialize_activity_hr_zones)

    @mcp.tool()
    def activity_metrics_describe(activity_id: int) -> dict[str, Any]:
        """Describe the dynamic metric schema of an activity's detail stream. Returns one row per metric descriptor: key, unit, metricsIndex. Use this to discover what metrics a watch recorded for a specific activity before requesting samples."""
        _validate_positive_id(activity_id, "activity_id")
        return _run_tool(config, lambda: get_activity_details(activity_id), serialize_metrics_descriptors)
