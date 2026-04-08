"""MCP server exposing Garmin Connect endpoints as tools via MCPServer."""
from __future__ import annotations

import os
from datetime import date
from typing import Any

import garth
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from garmin_cli.auth import _probe_session, _secure_directory, ensure_authenticated
from garmin_cli.config import CliConfig
from garmin_cli.endpoints._base import extract_status_code
from garmin_cli.endpoints.activities import (
    get_activity,
    get_activity_weather,
    list_activities,
)
from garmin_cli.endpoints.devices import get_devices
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
from garmin_cli.endpoints.metrics import (
    get_endurance_score_range,
    get_hill_score_range,
    get_race_predictions,
)
from garmin_cli.endpoints.performance import (
    get_all_thresholds,
    get_lactate_threshold,
    get_latest_vo2max,
    get_vo2max,
)
from garmin_cli.endpoints.workouts import (
    get_calendar_range,
    get_workout,
    list_workouts,
)
from garmin_cli.exceptions import GarminCliError
from garmin_cli.serializers import (
    serialize_activity_summary,
    serialize_body_battery,
    serialize_calendar_workout,
    serialize_daily_summary,
    serialize_device,
    serialize_endurance_score,
    serialize_hrv,
    serialize_hill_score,
    serialize_intensity_minutes,
    serialize_race_predictions,
    serialize_resting_hr,
    serialize_sleep,
    serialize_spo2,
    serialize_steps,
    serialize_stress,
    serialize_thresholds,
    serialize_training_readiness,
    serialize_training_status,
    serialize_vo2max,
    serialize_weight,
    serialize_workout_detail,
    serialize_workout_summary,
    serialize_zones,
)

_MAX_DAYS = 90
_WEATHER_FIELDS = ("temperature", "weatherIconCode", "windSpeed", "windDirectionDegrees", "humidity", "precipProbability")


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ToolError(f"Invalid date format for {name}: expected YYYY-MM-DD, got '{value}'") from exc


def _parse_date_range(start_date: str, end_date: str) -> tuple[date, date]:
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start > end:
        raise ToolError(f"start_date must be on or before end_date: {start} > {end}")
    span = (end - start).days + 1
    if span > _MAX_DAYS:
        raise ToolError(f"Date range cannot exceed {_MAX_DAYS} days (got {span} days)")
    return start, end


def _validate_positive_id(value: int, name: str) -> int:
    if value <= 0:
        raise ToolError(f"{name} must be a positive integer, got {value}")
    return value


def _validate_limit(value: int) -> int:
    if value < 1 or value > 100:
        raise ToolError(f"limit must be between 1 and 100, got {value}")
    return value


def _validate_start_offset(value: int) -> int:
    if value < 0:
        raise ToolError(f"start offset must be >= 0, got {value}")
    return value


def _envelope(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"count": len(rows), "rows": rows}


def _handle_error(exc: GarminCliError) -> ToolError:
    msg = exc.error
    if exc.error_code == "AUTH_MISSING":
        msg = f"{msg} Run `garmin-cli login` to authenticate interactively."
    return ToolError(msg)


def _latest_vo2max_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    dated_rows = [
        row for row in rows if isinstance(row.get("date"), str) and row.get("date")
    ]
    if not dated_rows:
        return rows[:1]
    latest_date = max(row["date"] for row in dated_rows)
    return [row for row in rows if row.get("date") == latest_date]


def create_mcp_server(config: CliConfig) -> MCPServer:
    """Create an MCPServer with Garmin Connect tools.

    Args:
        config: CLI configuration (garth_home, credentials, etc.)
            captured by closure so every tool call has access.
    """
    mcp = MCPServer("garmin")

    # -- Health tools -------------------------------------------------------

    @mcp.tool()
    def health_sleep(start_date: str, end_date: str) -> dict[str, Any]:
        """Get sleep data for a date range (YYYY-MM-DD). Returns date, duration_hours, deep/light/rem/awake minutes, and sleep score."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_sleep(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_sleep(raw))

    @mcp.tool()
    def health_hrv(start_date: str, end_date: str) -> dict[str, Any]:
        """Get HRV data for a date range (YYYY-MM-DD). Returns date, weekly_avg, last_night, status."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_hrv(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_hrv(raw))

    @mcp.tool()
    def health_weight(start_date: str, end_date: str) -> dict[str, Any]:
        """Get weight data for a date range (YYYY-MM-DD). Returns date, weight_kg, bmi, body_fat_pct."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_weight(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_weight(raw))

    @mcp.tool()
    def health_daily_summary(start_date: str, end_date: str) -> dict[str, Any]:
        """Get daily summary data for a date range (YYYY-MM-DD). Returns date, total_steps, distance_km, calories, floors, intensity minutes, and resting heart rate. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_daily_summary_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_daily_summary(raw))

    @mcp.tool()
    def health_steps(start_date: str, end_date: str) -> dict[str, Any]:
        """Get steps data for a date range (YYYY-MM-DD). Returns date, total_steps, total_distance, step_goal."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_steps_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_steps(raw))

    @mcp.tool()
    def health_intensity_minutes(start_date: str, end_date: str) -> dict[str, Any]:
        """Get intensity minutes for a date range (YYYY-MM-DD). Returns date, moderate_value, vigorous_value, weekly_goal."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_intensity_minutes_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_intensity_minutes(raw))

    @mcp.tool()
    def health_body_battery(start_date: str, end_date: str) -> dict[str, Any]:
        """Get body battery for a date range (YYYY-MM-DD). Returns date, start_level, end_level. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_body_battery_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_body_battery(raw))

    @mcp.tool()
    def health_stress(start_date: str, end_date: str) -> dict[str, Any]:
        """Get stress data for a date range (YYYY-MM-DD). Returns date, avg_stress, max_stress. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_stress_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_stress(raw))

    @mcp.tool()
    def health_spo2(start_date: str, end_date: str) -> dict[str, Any]:
        """Get SpO2 data for a date range (YYYY-MM-DD). Returns date, avg_spo2, lowest_spo2. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_spo2_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_spo2(raw))

    @mcp.tool()
    def health_resting_hr(start_date: str, end_date: str) -> dict[str, Any]:
        """Get resting heart rate for a date range (YYYY-MM-DD). Returns date, resting_hr. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_resting_hr_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_resting_hr(raw))

    @mcp.tool()
    def health_readiness(start_date: str, end_date: str) -> dict[str, Any]:
        """Get training readiness for a date range (YYYY-MM-DD). Returns date, score, level. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_training_readiness_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_training_readiness(raw))

    @mcp.tool()
    def health_training_status(date: str) -> dict[str, Any]:
        """Get training status for a single date (YYYY-MM-DD). Returns date, training_status, load_type."""
        parsed = _parse_date(date, "date")
        try:
            ensure_authenticated(config)
            raw = get_training_status(parsed)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_training_status(raw))

    # -- Activity tools -----------------------------------------------------

    @mcp.tool()
    def activity_list(
        limit: int = 20,
        start: int = 0,
        activity_type: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        """List recent activities. Returns id, date, name, type, distance_km, duration_min, avg_hr."""
        _validate_limit(limit)
        _validate_start_offset(start)
        try:
            ensure_authenticated(config)
            raw = list_activities(limit, start, activity_type, search)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_activity_summary(raw))

    @mcp.tool()
    def activity_get(activity_id: int) -> dict[str, Any]:
        """Get a single activity by ID. Returns id, date, name, type, distance_km, duration_min, avg_hr."""
        _validate_positive_id(activity_id, "activity_id")
        try:
            ensure_authenticated(config)
            raw = get_activity(activity_id)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_activity_summary(raw))

    @mcp.tool()
    def activity_weather(activity_id: int) -> dict[str, Any]:
        """Get weather for an activity. Returns temperature, weatherIconCode, windSpeed, windDirectionDegrees, humidity, precipProbability."""
        _validate_positive_id(activity_id, "activity_id")
        try:
            ensure_authenticated(config)
            raw = get_activity_weather(activity_id)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        if isinstance(raw, dict) and raw:
            rows = [{k: raw.get(k) for k in _WEATHER_FIELDS}]
        else:
            rows = []
        return _envelope(rows)

    # -- Workout tools ------------------------------------------------------

    @mcp.tool()
    def workout_list(limit: int = 20) -> dict[str, Any]:
        """List saved workouts. Returns id, name, sport, duration_min, description."""
        _validate_limit(limit)
        try:
            ensure_authenticated(config)
            raw = list_workouts(limit)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_workout_summary(raw))

    @mcp.tool()
    def workout_get(workout_id: int) -> dict[str, Any]:
        """Get workout detail by ID. Returns id, name, sport, duration_min, description, steps_summary, steps[]."""
        _validate_positive_id(workout_id, "workout_id")
        try:
            ensure_authenticated(config)
            raw = get_workout(workout_id)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_workout_detail(raw))

    @mcp.tool()
    def workout_calendar(start_date: str, end_date: str) -> dict[str, Any]:
        """Get scheduled workouts for a date range (YYYY-MM-DD). Returns date, id, name, type, duration_min, description."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_calendar_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        rows = serialize_calendar_workout({"calendarItems": raw})
        return _envelope(rows)

    # -- Performance tools --------------------------------------------------

    @mcp.tool()
    def performance_race_predictions() -> dict[str, Any]:
        """Get latest race predictions. Returns race_type, predicted_time_seconds, distance_meters."""
        try:
            ensure_authenticated(config)
            raw = get_race_predictions()
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_race_predictions(raw))

    @mcp.tool()
    def performance_endurance_score(start_date: str, end_date: str) -> dict[str, Any]:
        """Get endurance score for a date range (YYYY-MM-DD). Returns date, overall_score, endurance_classification."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_endurance_score_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_endurance_score(raw))

    @mcp.tool()
    def performance_hill_score(start_date: str, end_date: str) -> dict[str, Any]:
        """Get hill score for a date range (YYYY-MM-DD). Returns date, overall_score, endurance_score, strength_score."""
        start, end = _parse_date_range(start_date, end_date)
        try:
            ensure_authenticated(config)
            raw = get_hill_score_range(start, end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_hill_score(raw))

    @mcp.tool()
    def performance_thresholds() -> dict[str, Any]:
        """Get all available threshold metrics. Returns sport, lt_hr_bpm, lt_pace, ftp_watts, weight_kg."""
        try:
            ensure_authenticated(config)
            raw = get_all_thresholds()
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_thresholds(raw))

    @mcp.tool()
    def performance_vo2max(date: str | None = None) -> dict[str, Any]:
        """Get VO2 max. Pass a date (YYYY-MM-DD) for a specific day, or omit for latest. Returns date, vo2max, sport."""
        try:
            ensure_authenticated(config)
            if date is not None:
                parsed = _parse_date(date, "date")
                raw = get_vo2max(parsed)
            else:
                raw = get_latest_vo2max()
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        rows = serialize_vo2max(raw)
        if date is None:
            rows = _latest_vo2max_rows(rows)
        return _envelope(rows)

    @mcp.tool()
    def performance_zones() -> dict[str, Any]:
        """Get lactate-threshold-derived zone inputs. Returns sport, lt_hr_bpm, lt_pace."""
        try:
            ensure_authenticated(config)
            raw = get_lactate_threshold()
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_zones(raw))

    # -- Device tools -------------------------------------------------------

    @mcp.tool()
    def device_list() -> dict[str, Any]:
        """List registered Garmin devices. Returns device_id, display_name, device_type, last_sync_time."""
        try:
            ensure_authenticated(config)
            raw = get_devices()
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_device(raw))

    # -- Login status -------------------------------------------------------

    @mcp.tool()
    def login_status() -> dict[str, Any]:
        """Check authentication status. Returns authenticated (bool) and garth_home path. Never raises for missing sessions."""
        garth_home = os.path.expanduser(config.garth_home)
        authenticated = False
        try:
            _secure_directory(garth_home)
            garth.resume(garth_home)
            try:
                _probe_session(garth)
                authenticated = True
            except Exception as exc:
                if extract_status_code(exc) not in (401, 403):
                    raise GarminCliError(
                        error="Saved Garmin session could not be validated.",
                        error_code="AUTH_FAILED",
                    ) from exc
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ToolError(f"Cannot access session directory: {exc}") from exc
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        except Exception:
            pass  # garth session expired/corrupt -- report as not authenticated
        return {"authenticated": authenticated, "garth_home": garth_home}

    return mcp
