"""MCP server exposing Garmin Connect endpoints as tools via MCPServer."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from garmin_cli import backend as garth
from garmin_cli.auth import _probe_session, _secure_directory, ensure_authenticated
from garmin_cli.config import CliConfig
from garmin_cli.endpoints._base import extract_status_code
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
from garmin_cli.metrics.registry import LAP_SWIM_TYPE_KEYS
from garmin_cli.metrics.sport_profile import profile_for
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
    create_workout,
    delete_workout,
    get_calendar_range,
    get_workout,
    list_workouts,
    schedule_workout,
    update_workout,
)
from garmin_cli.exceptions import GarminCliError
from garmin_cli.workout_builder import build_garmin_payload, merge_workout_payload
from garmin_cli.workout_schema import validate_workout_input
from garmin_cli.serializers import (
    COLUMNS_ACTIVITY_WEATHER,
    select_latest_dated_rows,
    serialize_activity_detail,
    serialize_activity_hr_zones,
    serialize_activity_laps,
    serialize_activity_summary,
    serialize_capability_manifest,
    serialize_metrics_descriptors,
    serialize_multisport_children,
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

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WriteLogEvent:
    """Structured payload for a single write-tool invocation log line.

    Only metadata is captured -- workout ``name`` and ``description`` are
    reduced to length-only integers so PII never lands in logs. Bearer tokens
    are never read into this struct.
    """

    tool: str
    outcome: str
    dry_run: bool = False
    workout_id: int | None = None
    errors_count: int | None = None
    name_len: int | None = None
    description_len: int | None = None


def _emit_write_log(event: WriteLogEvent) -> None:
    _logger.info("workout_write", extra={"event": event.__dict__})


def _workout_name_len(workout: Any) -> int | None:
    if isinstance(workout, dict):
        name = workout.get("name")
        if isinstance(name, str):
            return len(name)
    return None


def _workout_description_len(workout: Any) -> int | None:
    if isinstance(workout, dict):
        description = workout.get("description")
        if isinstance(description, str):
            return len(description)
    return None


def _extract_workout_id(raw: Any) -> int | None:
    if not isinstance(raw, dict):
        return None
    wid = raw.get("workoutId")
    if isinstance(wid, bool):
        return None
    if isinstance(wid, int):
        return wid
    if isinstance(wid, str) and wid.isdigit():
        return int(wid)
    return None


def _validation_envelope(errors: list[str]) -> dict[str, Any]:
    return _envelope(
        [{"ok": False, "error_code": "INVALID_INPUT", "errors": list(errors)}]
    )


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


def _fetch_one_activity_laps(activity: dict[str, Any], activity_id: Any) -> list[dict[str, Any]]:
    profile = profile_for(activity_type_key(activity))
    if profile.type_keys & LAP_SWIM_TYPE_KEYS:
        splits_payload = get_activity_typed_splits(activity_id)
    else:
        splits_payload = get_activity_splits(activity_id)
    return serialize_activity_laps(activity, splits_payload, profile)


def _fetch_laps_rows_for_activity(activity: dict[str, Any], activity_id: Any) -> list[dict[str, Any]]:
    """Fetch laps; for multisport parents, fan out to children with leg_index."""
    if is_multisport_parent(activity):
        children = get_multisport_children(activity)
        if children:
            rows: list[dict[str, Any]] = []
            for idx, child in enumerate(children):
                child_id = child.get("activityId")
                if child_id is None:
                    continue
                child_rows = _fetch_one_activity_laps(child, child_id)
                for row in child_rows:
                    row["leg_index"] = idx
                rows.extend(child_rows)
            return rows
    return _fetch_one_activity_laps(activity, activity_id)


def create_mcp_server(
    config: CliConfig,
    *,
    token_verifier: TokenVerifier | None = None,
    auth: AuthSettings | None = None,
) -> MCPServer:
    """Create an MCPServer with Garmin Connect tools.

    Args:
        config: CLI configuration (session home, credentials, etc.)
            captured by closure so every tool call has access.
        token_verifier: Optional bearer-token verifier; when supplied along
            with ``auth`` the MCP SDK gates all tools on non-loopback
            transports. Loopback / stdio callers should leave both as
            ``None``.
        auth: Optional auth settings; required by the SDK when
            ``token_verifier`` is set.
    """
    mcp_kwargs: dict[str, Any] = {}
    if token_verifier is not None:
        mcp_kwargs["token_verifier"] = token_verifier
    if auth is not None:
        mcp_kwargs["auth"] = auth
    mcp = MCPServer("garmin", **mcp_kwargs)

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
        try:
            ensure_authenticated(config)
            raw = list_activities(limit, start, activity_type, search, parsed_start, parsed_end)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_activity_summary(raw))

    @mcp.tool()
    def activity_get(activity_id: int, detail: bool = False) -> dict[str, Any]:
        """Get a single activity by ID. For multisport activities (triathlon etc.), includes child activities with per-sport details. Returns compact activity fields by default, or extended sport-aware metrics including running dynamics (GCT, vertical oscillation/ratio, stride length), cycling power suite (avg/max/normalized power, TSS, IF), swim aggregates (SWOLF, strokes), and training response (aerobic/anaerobic training effect, vO2max, recovery time) when detail=True. When detail=True, the response carries an additional ``unavailable`` array (when non-empty) annotating which registry-known metrics are not applicable to this sport (``not_applicable_to_sport``) or unexpectedly absent (``absent_in_response``)."""
        _validate_positive_id(activity_id, "activity_id")
        try:
            ensure_authenticated(config)
            raw = get_activity(activity_id)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        rows = serialize_activity_detail(raw) if detail else serialize_activity_summary(raw)
        result = _envelope(rows)
        children: list[dict[str, Any]] = []
        if is_multisport_parent(raw):
            try:
                fetched = get_multisport_children(raw)
            except GarminCliError as exc:
                raise _handle_error(exc) from exc
            if fetched:
                children = fetched
                result["children"] = serialize_multisport_children(fetched)
        if detail:
            manifest: list[dict[str, Any]] = []
            if children:
                for idx, child in enumerate(children):
                    child_row = serialize_activity_detail(child)
                    child_projected = child_row[0] if child_row else None
                    manifest.extend(serialize_capability_manifest(
                        child, child_projected, leg_index=idx,
                    ))
            else:
                projected = rows[0] if rows else None
                manifest = serialize_capability_manifest(raw, projected)
            if manifest:
                result["unavailable"] = manifest
        return result

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
            rows = [{k: raw.get(k) for k in COLUMNS_ACTIVITY_WEATHER}]
        else:
            rows = []
        return _envelope(rows)

    @mcp.tool()
    def activity_laps(activity_id: int) -> dict[str, Any]:
        """Get lap-by-lap data for an activity. For pool-swim activities returns per-pool-length rows with SWOLF, stroke type, and stroke counts; for run/bike activities returns per-lap rows with HR, power (cycling), and running dynamics. For multisport parents (triathlon etc.), returns each child leg's laps concatenated with a 0-based ``leg_index`` stamped on every row."""
        _validate_positive_id(activity_id, "activity_id")
        try:
            ensure_authenticated(config)
            activity = get_activity(activity_id)
            rows = _fetch_laps_rows_for_activity(activity, activity_id)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(rows)

    @mcp.tool()
    def activity_hr_zones(activity_id: int) -> dict[str, Any]:
        """Get HR time-in-zone breakdown for an activity. Returns one row per zone: zone, zone_low_bpm, zone_high_bpm, seconds_in_zone, minutes_in_zone."""
        _validate_positive_id(activity_id, "activity_id")
        try:
            ensure_authenticated(config)
            raw = get_activity_hr_in_timezones(activity_id)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_activity_hr_zones(raw))

    @mcp.tool()
    def activity_metrics_describe(activity_id: int) -> dict[str, Any]:
        """Describe the dynamic metric schema of an activity's detail stream. Returns one row per metric descriptor: key, unit, metricsIndex. Use this to discover what metrics a watch recorded for a specific activity before requesting samples."""
        _validate_positive_id(activity_id, "activity_id")
        try:
            ensure_authenticated(config)
            raw = get_activity_details(activity_id)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return _envelope(serialize_metrics_descriptors(raw))

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

    @mcp.tool()
    def workout_create(
        workout: dict[str, Any], dry_run: bool = False
    ) -> dict[str, Any]:
        """Create a new workout from a simplified schema dict.

        The ``workout`` parameter accepts:
          - name (str, required, 1-256 chars)
          - sport (str, required): cycling, fitness_equipment, hiking,
            multi_sport, other, running, swimming, walking
          - steps (list[dict], required, non-empty)
          - description (str, optional)

        Each step is either a regular step or a ``repeat`` step.

        Regular step shape: {"type": <step_type>, "duration": {"type": "time"
        or "distance", "value": <number>}, "target": {<target>}}
          - step_type: warmup, cooldown, interval, recovery, rest.
          - duration "type" is "time" (seconds) or "distance" (meters).
          - Targets split into two shapes:
            * Zone-based (heart.rate.zone, power.zone): {"type":
              "<zone_type>", "zone": <int 1-5>}. Use this for HR or power
              zones, including watt ranges expressed as a zone number.
            * Range-based (speed.zone, cadence.zone): {"type":
              "<range_type>", "min": <number>, "max": <number>}.
            * Generic: {"type": "no.target"} or {"type": "open"}.

        Repeat shape: {"type": "repeat", "count": <int 1-99>, "steps":
        [<nested steps>]}.

        Example::

            {"name": "Easy Run", "sport": "running", "steps": [
                {"type": "interval",
                 "duration": {"type": "time", "value": 1800},
                 "target": {"type": "heart.rate.zone", "zone": 2}}]}

        Set ``dry_run=True`` to validate and resolve the wire payload
        without creating the workout. In dry-run mode no Garmin API call
        is made.

        On validation failure, returns one row with ``ok: False,
        error_code: "INVALID_INPUT", errors: [<field-path messages>]``.
        On success, returns ``ok: True, action: "created", workout_id``.
        """
        errors = validate_workout_input(workout, partial=False)
        if errors:
            _emit_write_log(WriteLogEvent(
                tool="workout_create",
                outcome="failed-validation",
                dry_run=dry_run,
                errors_count=len(errors),
                name_len=_workout_name_len(workout),
                description_len=_workout_description_len(workout),
            ))
            return _validation_envelope(errors)

        payload = build_garmin_payload(workout)

        if dry_run:
            _emit_write_log(WriteLogEvent(
                tool="workout_create",
                outcome="dry-run",
                dry_run=True,
                name_len=_workout_name_len(workout),
                description_len=_workout_description_len(workout),
            ))
            return _envelope([{
                "ok": True,
                "dry_run": True,
                "wire_payload": payload,
                "validation_report": {"ok": True},
            }])

        try:
            ensure_authenticated(config)
            raw = create_workout(payload)
        except GarminCliError as exc:
            outcome = "failed-auth" if exc.error_code in ("AUTH_MISSING", "AUTH_FAILED") else "failed-upstream"
            _emit_write_log(WriteLogEvent(
                tool="workout_create",
                outcome=outcome,
                dry_run=False,
                name_len=_workout_name_len(workout),
                description_len=_workout_description_len(workout),
            ))
            raise _handle_error(exc) from exc

        workout_id = _extract_workout_id(raw)
        _emit_write_log(WriteLogEvent(
            tool="workout_create",
            outcome="success",
            dry_run=False,
            workout_id=workout_id,
            name_len=_workout_name_len(workout),
            description_len=_workout_description_len(workout),
        ))
        return _envelope([{
            "ok": True,
            "action": "created",
            "workout_id": workout_id,
        }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def workout_schedule(workout_id: int, date: str) -> dict[str, Any]:
        """Schedule a saved workout on a calendar date (YYYY-MM-DD).

        Destructive: a scheduled date is added to the user's training calendar.
        Returns ``ok: True, action: "scheduled", workout_id,
        workout_schedule_id, date`` on success.
        """
        _validate_positive_id(workout_id, "workout_id")
        parsed_date = _parse_date(date, "date")
        try:
            ensure_authenticated(config)
            raw = schedule_workout(workout_id, parsed_date)
        except GarminCliError as exc:
            outcome = "failed-auth" if exc.error_code in ("AUTH_MISSING", "AUTH_FAILED") else "failed-upstream"
            _emit_write_log(WriteLogEvent(
                tool="workout_schedule",
                outcome=outcome,
                workout_id=workout_id,
            ))
            raise _handle_error(exc) from exc

        raw_dict = raw if isinstance(raw, dict) else {}
        _emit_write_log(WriteLogEvent(
            tool="workout_schedule",
            outcome="success",
            workout_id=workout_id,
        ))
        return _envelope([{
            "ok": True,
            "action": "scheduled",
            "workout_id": workout_id,
            "workout_schedule_id": raw_dict.get("workoutScheduleId"),
            "date": raw_dict.get("calendarDate") or parsed_date.isoformat(),
        }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def workout_update(
        workout_id: int,
        workout: dict[str, Any],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Update an existing workout. Merge semantics: pass only the fields
        you want to change; omitted fields are preserved from the existing
        record (matches the ``garmin-cli workout update`` CLI behavior).

        Destructive: the workout's saved structure is replaced. Read-only
        fields (workoutId, ownerId, createdDate, atpPlanId) are preserved.

        Set ``dry_run=True`` to preview the merged wire payload without
        writing. Dry-run still performs one Garmin read (``get_workout``)
        because the merge needs the existing payload, but performs no write.

        On validation failure: ``ok: False, error_code: "INVALID_INPUT",
        errors: [...]``. On success: ``ok: True, action: "updated",
        workout_id``.
        """
        _validate_positive_id(workout_id, "workout_id")
        errors = validate_workout_input(workout, partial=True)
        if errors:
            _emit_write_log(WriteLogEvent(
                tool="workout_update",
                outcome="failed-validation",
                dry_run=dry_run,
                workout_id=workout_id,
                errors_count=len(errors),
                name_len=_workout_name_len(workout),
                description_len=_workout_description_len(workout),
            ))
            return _validation_envelope(errors)

        try:
            ensure_authenticated(config)
            existing = get_workout(workout_id)
            merged, warnings = merge_workout_payload(existing, workout)
        except GarminCliError as exc:
            outcome = "failed-auth" if exc.error_code in ("AUTH_MISSING", "AUTH_FAILED") else "failed-upstream"
            _emit_write_log(WriteLogEvent(
                tool="workout_update",
                outcome=outcome,
                dry_run=dry_run,
                workout_id=workout_id,
                name_len=_workout_name_len(workout),
                description_len=_workout_description_len(workout),
            ))
            raise _handle_error(exc) from exc

        if dry_run:
            _emit_write_log(WriteLogEvent(
                tool="workout_update",
                outcome="dry-run",
                dry_run=True,
                workout_id=workout_id,
                name_len=_workout_name_len(workout),
                description_len=_workout_description_len(workout),
            ))
            return _envelope([{
                "ok": True,
                "dry_run": True,
                "wire_payload": merged,
                "validation_report": {
                    "ok": True,
                    "warnings": list(warnings),
                },
            }])

        # update_workout routes through _write_request(capability="workout_update"),
        # i.e. the governed raw fallback. R9 in the plan defers migration off
        # RAW_FALLBACKS until python-garminconnect exposes a typed helper.
        try:
            update_workout(workout_id, merged)
        except GarminCliError as exc:
            _emit_write_log(WriteLogEvent(
                tool="workout_update",
                outcome="failed-upstream",
                dry_run=False,
                workout_id=workout_id,
                name_len=_workout_name_len(workout),
                description_len=_workout_description_len(workout),
            ))
            raise _handle_error(exc) from exc

        _emit_write_log(WriteLogEvent(
            tool="workout_update",
            outcome="success",
            dry_run=False,
            workout_id=workout_id,
            name_len=_workout_name_len(workout),
            description_len=_workout_description_len(workout),
        ))
        return _envelope([{
            "ok": True,
            "action": "updated",
            "workout_id": workout_id,
        }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def workout_delete(workout_id: int) -> dict[str, Any]:
        """Delete a saved workout by ID.

        Destructive: the workout is permanently removed. Returns
        ``ok: True, action: "deleted", workout_id`` on success.
        """
        _validate_positive_id(workout_id, "workout_id")
        try:
            ensure_authenticated(config)
            delete_workout(workout_id)
        except GarminCliError as exc:
            outcome = "failed-auth" if exc.error_code in ("AUTH_MISSING", "AUTH_FAILED") else "failed-upstream"
            _emit_write_log(WriteLogEvent(
                tool="workout_delete",
                outcome=outcome,
                workout_id=workout_id,
            ))
            raise _handle_error(exc) from exc

        _emit_write_log(WriteLogEvent(
            tool="workout_delete",
            outcome="success",
            workout_id=workout_id,
        ))
        return _envelope([{
            "ok": True,
            "action": "deleted",
            "workout_id": workout_id,
        }])

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
            rows = select_latest_dated_rows(rows)
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
        """Check authentication status. Returns authenticated (bool) and garmin_home path. Never raises for missing sessions."""
        garmin_home = os.path.expanduser(config.garth_home)
        authenticated = False
        try:
            _secure_directory(garmin_home)
            garth.resume(garmin_home)
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
        return {"authenticated": authenticated, "garmin_home": garmin_home}

    return mcp
