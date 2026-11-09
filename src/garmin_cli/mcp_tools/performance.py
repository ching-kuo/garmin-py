"""Performance MCP tools (race predictions, endurance/hill score, thresholds, VO2 max, zones, trends)."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from garmin_cli.config import CliConfig
from garmin_cli.endpoints.metrics import (
    MAX_FASTEST_SPLITS_BESTS,
    FastestSplitsSport,
    FtpHistorySport,
    PowerCurveSport,
    get_acclimation_range,
    get_cycling_ability_range,
    get_endurance_score_range,
    get_fastest_splits,
    get_ftp_history,
    get_hill_score_range,
    get_power_curve,
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
from garmin_cli.mcp_tools._schemas import Envelope
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
from garmin_cli.serializers.trends import (
    serialize_acclimation,
    serialize_cycling_ability,
    serialize_fastest_splits,
    serialize_ftp_history,
    serialize_power_curve,
)
from garmin_cli.services.performance import fetch_vo2max


def register_performance_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register the performance-domain read tools on ``mcp``."""

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_race_predictions() -> Envelope:
        """Get latest race predictions. Returns race_type, predicted_time_seconds, distance_meters."""
        return _run_tool(config, get_race_predictions, serialize_race_predictions)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_personal_records() -> Envelope:
        """Get all-time personal records. Returns type_id, label, value, activity_type, date, activity_id, activity_name. Label suffix gives units (_s seconds, _m meters, _w watts); records with an unmapped Garmin type_id have label null with the raw value."""
        return _run_tool(config, get_personal_records, serialize_personal_records)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_endurance_score(start_date: str, end_date: str) -> Envelope:
        """Get endurance score for a date range (YYYY-MM-DD). Returns date, overall_score, endurance_classification."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_endurance_score_range(start, end), serialize_endurance_score)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_hill_score(start_date: str, end_date: str) -> Envelope:
        """Get hill score for a date range (YYYY-MM-DD). Returns date, overall_score, endurance_score, strength_score."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_hill_score_range(start, end), serialize_hill_score)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_thresholds() -> Envelope:
        """Get all available threshold metrics. Returns sport, lt_hr_bpm, lt_pace, ftp_watts, weight_kg."""
        return _run_tool(config, get_all_thresholds, serialize_thresholds)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_vo2max(date: str | None = None) -> Envelope:
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
    def performance_zones() -> Envelope:
        """Get lactate-threshold-derived zone inputs. Returns sport, lt_hr_bpm, lt_pace."""
        return _run_tool(config, get_lactate_threshold, serialize_zones)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_ftp_history(
        start_date: str, end_date: str, sport: FtpHistorySport = "cycling"
    ) -> Envelope:
        """Get daily functional threshold power (FTP) for a date range (YYYY-MM-DD). Returns date, sport, ftp_watts."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_ftp_history(start, end, sport), serialize_ftp_history)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_acclimation(start_date: str, end_date: str) -> Envelope:
        """Get daily heat and altitude acclimation for a date range (YYYY-MM-DD). Returns date, heat_acclimation_pct, heat_trend, altitude_acclimation, altitude_trend, current_altitude."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_acclimation_range(start, end), serialize_acclimation)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_cycling_ability(start_date: str, end_date: str) -> Envelope:
        """Get daily cycling ability scores for a date range (YYYY-MM-DD). Returns date, aerobic_endurance, aerobic_capacity, anaerobic_capacity (0-100 scores), profile_type, and a Garmin feedback key per score."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_cycling_ability_range(start, end), serialize_cycling_ability)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_power_curve(
        start_date: str, end_date: str, sport: PowerCurveSport = "cycling"
    ) -> Envelope:
        """Get the power curve (best average power per duration) across activities in a date range (YYYY-MM-DD). Returns duration_s, power_w, activity_id, activity_date. Garmin supports cycling and rowing only."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_power_curve(start, end, sport), serialize_power_curve)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def performance_fastest_splits(
        start_date: str,
        end_date: str,
        sport: FastestSplitsSport = "running",
        bests_per_distance: int = 1,
    ) -> Envelope:
        """Get the fastest times per standard distance (running: 1 km, 1 mi, 5 km, 10 km, half marathon) across activities in a date range (YYYY-MM-DD). Returns distance_m, time_s, activity_id, activity_date; bests_per_distance (1-10) sets how many efforts per distance."""
        if not 1 <= bests_per_distance <= MAX_FASTEST_SPLITS_BESTS:
            raise ToolError(
                f"bests_per_distance must be between 1 and {MAX_FASTEST_SPLITS_BESTS}, got {bests_per_distance}"
            )
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(
            config,
            lambda: get_fastest_splits(start, end, sport, bests_per_distance),
            serialize_fastest_splits,
        )
