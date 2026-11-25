"""Activity MCP tools (list, get, weather, laps, HR zones, metrics-describe)."""
from __future__ import annotations

from typing import Any, cast

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic.json_schema import SkipJsonSchema

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
    StrictId,
    _authenticated,
    _envelope,
    _parse_date_range,
    _run_tool,
    _validate_limit,
    _validate_positive_id,
)
from garmin_cli.mcp_tools._schemas import (
    ActivityDetailMetricsEnvelope,
    ActivityGetEnvelope,
    Envelope,
)
from garmin_cli.serializers import (
    serialize_activity_detail,
    serialize_activity_hr_zones,
    serialize_activity_laps,
    serialize_activity_summary,
    serialize_activity_weather,
    serialize_capability_manifest,
    serialize_detail_metrics,
    serialize_metrics_descriptors,
    serialize_multisport_children,
)
from garmin_cli.services.activities import (
    build_capability_manifest,
    downsample_rows,
    fetch_laps_for_activity,
)


_NOT_GIVEN: Any = object()  # default of the retired activity_list `start` argument


def _validate_offset(value: int) -> int:
    if value < 0:
        raise ToolError(f"offset must be >= 0, got {value}")
    return value


# Auto-fit budget for max_samples=0: samples x columns kept small enough that
# the doubled MCP payload (text content + structuredContent) stays under
# typical client tool-result token caps.
_AUTO_CELL_BUDGET = 2400


def _validate_max_samples(value: int) -> int:
    if value != 0 and (value < 100 or value > 5000):
        raise ToolError(f"max_samples must be between 100 and 5000 (or 0 for auto), got {value}")
    return value


def _auto_max_samples(rows: list[dict[str, Any]]) -> int:
    """Size the sample cap to the column count so payloads stay client-safe."""
    columns = max(1, len(rows[0])) if rows else 1
    return max(100, min(1000, _AUTO_CELL_BUDGET // columns))


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


def _activity_get_result(activity_id: int, detail: bool = False) -> ActivityGetEnvelope:
    """Build the shared activity-get payload used by tools and resources."""
    raw = get_activity(activity_id)
    rows = serialize_activity_detail(raw) if detail else serialize_activity_summary(raw)
    result = cast(ActivityGetEnvelope, dict(_envelope(rows)))
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


def register_activity_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register the activity-domain read tools on ``mcp``."""

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def activity_list(
        limit: int = 20,
        offset: int = 0,
        activity_type: str | None = None,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        # Unpublished: catches callers still sending the pre-3.0 name, which the
        # SDK would otherwise drop silently (paging from 0 again).
        start: SkipJsonSchema[Any] = _NOT_GIVEN,
    ) -> Envelope:
        """List activities newest first, optionally filtered by date range (YYYY-MM-DD). Returns id, date, name, type, distance_km, duration_min, avg_hr, training_load (per-activity Garmin training load).

        ``offset`` skips that many newest activities. ``truncated`` is true when a full page came back; pass ``next_offset`` as ``offset`` for the next page. ``activity_type`` is a Garmin activity typeKey such as running, cycling, swimming, walking, hiking, strength_training, or multi_sport.
        """
        if start is not _NOT_GIVEN:  # even an explicit null
            raise ToolError("activity_list has no 'start' parameter since 3.0; use offset")
        _validate_limit(limit)
        _validate_offset(offset)
        parsed_start = None
        parsed_end = None
        if (start_date is None) != (end_date is None):
            raise ToolError("start_date and end_date must be provided together")
        if start_date is not None and end_date is not None:
            parsed_start, parsed_end = _parse_date_range(start_date, end_date)
        result = _run_tool(
            config,
            lambda: list_activities(limit, offset, activity_type, search, parsed_start, parsed_end),
            serialize_activity_summary,
        )
        # Garmin reports no total, so a full page is the only "maybe more" signal.
        result["truncated"] = result["count"] == limit
        if result["truncated"]:
            result["next_offset"] = offset + limit
        return result

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def activity_get(activity_id: StrictId, detail: bool = False) -> ActivityGetEnvelope:
        """Get a single activity by ID. Use when you need whole-activity totals and averages; use activity_detail_metrics for per-sample time series. Multisport parents include their child legs in ``children``. detail=true adds sport-aware metrics (elapsed_time_min incl. stops vs moving duration_min, running dynamics, cycling power/TSS/IF and cadence, swim SWOLF/strokes, training effect/load, VO2max, recovery time), workout_id (the scheduled workout it executed, else null), and an ``unavailable`` list of metrics not applicable to the sport or absent upstream."""
        _validate_positive_id(activity_id, "activity_id")

        return _authenticated(config, lambda: _activity_get_result(activity_id, detail))

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def activity_weather(activity_id: StrictId) -> Envelope:
        """Get weather for an activity. Returns temp_c, apparent_temp_c, dew_point_c (Celsius), humidity (%), wind_speed, wind_gust, wind_direction (degrees), wind_direction_compass, and condition. No precipitation-probability field."""
        _validate_positive_id(activity_id, "activity_id")
        return _run_tool(config, lambda: get_activity_weather(activity_id), serialize_activity_weather)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def activity_laps(activity_id: StrictId, offset: int = 0) -> Envelope:
        """Get lap-by-lap data for an activity, capped at 100 rows. Use ``offset`` with ``next_offset`` to page. For pool-swim activities returns per-pool-length rows with SWOLF, stroke type, and stroke counts; for run/bike activities returns per-lap rows with start_time_gmt/start_time_local, HR, power and cadence (cycling), and running dynamics. For multisport parents (triathlon etc.), returns each child leg's laps concatenated with a 0-based ``leg_index`` stamped on every row."""
        _validate_positive_id(activity_id, "activity_id")
        _validate_offset(offset)
        return _authenticated(
            config,
            lambda: _envelope(
                _fetch_laps_rows_for_activity(get_activity(activity_id), activity_id),
                cap=100,
                offset=offset,
            ),
        )

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def activity_hr_zones(activity_id: StrictId) -> Envelope:
        """Get HR time-in-zone breakdown for an activity. Returns one row per zone: zone, zone_low_bpm, zone_high_bpm, seconds_in_zone, minutes_in_zone."""
        _validate_positive_id(activity_id, "activity_id")
        return _run_tool(config, lambda: get_activity_hr_in_timezones(activity_id), serialize_activity_hr_zones)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def activity_metrics_describe(activity_id: StrictId) -> Envelope:
        """Describe the dynamic metric schema of an activity's detail stream. Returns one row per metric descriptor: key, unit, metricsIndex. Use this to discover what metrics a watch recorded for a specific activity before requesting samples."""
        _validate_positive_id(activity_id, "activity_id")
        return _run_tool(config, lambda: get_activity_details(activity_id), serialize_metrics_descriptors)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def activity_detail_metrics(
        activity_id: StrictId,
        metrics: str = "",
        max_samples: int = 0,
    ) -> ActivityDetailMetricsEnvelope:
        """Get a deterministic stride sample of an activity metric stream. Use when you need per-sample time series (HR, power, pace over time); use activity_get for whole-activity totals. Every row carries all requested metrics keyed by metric key (e.g. directTimestamp, directHeartRate, directPower, directSpeed), so channels are always timestamp-aligned at any stride — fetch ALL channels you need in ONE call; never split channels across calls and stitch. Response size scales with samples x metrics: the default ``max_samples=0`` auto-sizes the sample count to the column count (~2400 total values, clamped to 100..1000 samples) so multi-channel pulls fit client response limits; pass 100..5000 to override, lowering it rather than dropping channels when a response is too large. Pass ``metrics`` as a comma-separated key list to reduce columns; use activity_metrics_describe to discover available keys."""
        _validate_positive_id(activity_id, "activity_id")
        _validate_max_samples(max_samples)
        wanted = tuple(m.strip() for m in metrics.split(",") if m.strip()) or None

        def produce() -> ActivityDetailMetricsEnvelope:
            rows = serialize_detail_metrics(get_activity_details(activity_id), wanted)
            sampled, stride = downsample_rows(rows, max_samples or _auto_max_samples(rows))
            result: dict[str, Any] = dict(_envelope(sampled))
            result.update({
                "samples_total": len(rows),
                "samples_returned": len(sampled),
                "stride": stride,
            })
            return cast(ActivityDetailMetricsEnvelope, result)

        # serialize inside the authenticated producer so an unknown-key
        # INVALID_INPUT is translated like any other GarminCliError.
        return _authenticated(config, produce)
