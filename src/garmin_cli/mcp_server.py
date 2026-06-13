"""MCP server exposing Garmin Connect endpoints as tools via MCPServer."""
from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, timedelta

# Alias so tools whose user-facing parameter is named ``date`` can still reach
# ``date.today()`` without the parameter shadowing the class.
date_cls = date
from typing import Any, Literal, TypeVar

WriteOutcome = Literal[
    "success",
    "dry-run",
    "failed-validation",
    "failed-auth",
    "failed-upstream",
]

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from garmin_cli import backend as garth
from garmin_cli.auth import _probe_session, _secure_directory, ensure_authenticated
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
from garmin_cli.exceptions import GarminCliError, extract_status_code
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
from garmin_cli.services.activities import (
    build_capability_manifest,
    fetch_laps_for_activity,
)

_MAX_DAYS = 90

_logger = logging.getLogger(__name__)

_T = TypeVar("_T")


@dataclass(frozen=True)
class WriteLogEvent:
    """Structured payload for a single write-tool invocation log line.

    Only metadata is captured -- workout ``name`` and ``description`` are
    reduced to length-only integers so PII never lands in logs. Bearer tokens
    are never read into this struct.
    """

    tool: str
    outcome: WriteOutcome
    dry_run: bool = False
    workout_id: int | None = None
    errors_count: int | None = None
    name_len: int | None = None
    description_len: int | None = None


def _emit_write_log(event: WriteLogEvent) -> None:
    _logger.info("workout_write", extra={"event": event.__dict__})


def _workout_str_len(workout: Any, key: str) -> int | None:
    if isinstance(workout, dict):
        value = workout.get(key)
        if isinstance(value, str):
            return len(value)
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


def _classify_garmin_error(exc: GarminCliError) -> WriteOutcome:
    if exc.error_code in ("AUTH_MISSING", "AUTH_FAILED"):
        return "failed-auth"
    return "failed-upstream"


class _WriteAudit:
    """Records exactly one structured log event for a write-tool invocation.

    Holds the invocation's invariant metadata (``tool``, ``dry_run``,
    ``workout_id``, ``name_len``, ``description_len``) as a base
    :class:`WriteLogEvent`; each terminal helper emits that base with the
    outcome (and any per-outcome field) filled in. A single ``_done`` guard
    ensures one and only one log line per invocation.
    """

    def __init__(self, base: WriteLogEvent) -> None:
        self._base = base
        self._done = False

    def _emit(self, **overrides: Any) -> None:
        _emit_write_log(replace(self._base, **overrides))
        self._done = True

    def fail_validation(self, errors_count: int) -> None:
        self._emit(outcome="failed-validation", errors_count=errors_count)

    def dry_run(self) -> None:
        self._emit(outcome="dry-run")

    def success(self, **overrides: Any) -> None:
        self._emit(outcome="success", **overrides)


@contextmanager
def _write_audit(base: WriteLogEvent) -> Iterator[_WriteAudit]:
    """Own the write-audit logging lifecycle for a single write tool.

    Yields a :class:`_WriteAudit` for terminal outcomes (validation failure,
    dry-run, success). If a :class:`GarminCliError` escapes the ``with`` body
    and no event has been recorded yet, the classified ``failed-auth`` /
    ``failed-upstream`` outcome is logged before the error is converted to the
    caller-facing :class:`ToolError` (same translation as the read tools).
    """
    audit = _WriteAudit(base)
    try:
        yield audit
    except GarminCliError as exc:
        if not audit._done:
            audit._emit(outcome=_classify_garmin_error(exc))
        raise _handle_error(exc) from exc


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


def _identity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return rows


def _weather_rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and raw:
        return [{k: raw.get(k) for k in COLUMNS_ACTIVITY_WEATHER}]
    return []


def _handle_error(exc: GarminCliError) -> ToolError:
    msg = exc.error
    if exc.error_code == "AUTH_MISSING":
        msg = f"{msg} Run `garmin-cli login` to authenticate interactively."
    return ToolError(msg)


def _fetch_laps_rows_for_activity(activity: dict[str, Any], activity_id: Any) -> list[dict[str, Any]]:
    """Fetch laps; for multisport parents, fan out to children with leg_index.

    Thin wrapper over :func:`garmin_cli.services.activities.fetch_laps_for_activity`
    that binds this module's endpoint/serializer references so test patches on
    ``garmin_cli.mcp_server.*`` stay effective. The service returns a
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


def _authenticated(config: CliConfig, produce: Callable[[], _T]) -> _T:
    """Ensure auth, run ``produce``, and translate GarminCliError to ToolError.

    Centralizes the ``ensure_authenticated(config)`` -> fetch -> ``except
    GarminCliError: raise _handle_error(exc)`` pattern. ``produce`` runs inside
    the same ``try`` so upstream Garmin errors are translated consistently.
    """
    try:
        ensure_authenticated(config)
        return produce()
    except GarminCliError as exc:
        raise _handle_error(exc) from exc


def _run_tool(
    config: CliConfig,
    fetch: Callable[[], Any],
    serialize: Callable[[Any], list[dict[str, Any]]] = _identity_rows,
) -> dict[str, Any]:
    """Auth, fetch, serialize, and envelope a read tool's rows.

    Collapses the read tools' identical 4-step body. Input parsing/validation
    stays in the tool (it must raise ``ToolError`` directly); ``serialize``
    defaults to identity for endpoints already returning row dicts.
    """
    return _envelope(serialize(_authenticated(config, fetch)))


# Only NOT_FOUND degrades to a per-section gap (the metric simply has no data
# for that window). Every other error -- auth, rate limiting, server/network,
# bad input, or any future/unknown code -- fails the whole snapshot, which
# would otherwise be silently partial and untrustworthy. An allowlist makes the
# safe direction (fail loudly) the default for codes not enumerated here.
_SNAPSHOT_RECOVERABLE_CODES: frozenset[str] = frozenset({"NOT_FOUND"})

# One report section: a stable name, a thunk that fetches raw upstream data,
# and a serializer that turns it into rows.
ReportSection = tuple[str, Callable[[], Any], Callable[[Any], list[dict[str, Any]]]]


def _collect_report_sections(
    specs: list[ReportSection],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """Fan out a report's sections, isolating recoverable per-section gaps.

    Returns ``(sections, unavailable)``. A section that raises a NOT_FOUND
    ``GarminCliError`` or returns no rows is recorded as an empty list and noted
    in ``unavailable`` with a ``reason`` (``not_found`` / ``no_data``). Any other
    ``GarminCliError`` propagates so the caller's auth wrapper converts it to a
    ``ToolError`` and the whole snapshot fails loudly.
    """
    sections: dict[str, list[dict[str, Any]]] = {}
    unavailable: list[dict[str, str]] = []
    for name, fetch, serialize in specs:
        try:
            rows = serialize(fetch())
        except GarminCliError as exc:
            if exc.error_code not in _SNAPSHOT_RECOVERABLE_CODES:
                raise
            sections[name] = []
            unavailable.append({"section": name, "reason": exc.error_code.lower()})
            continue
        sections[name] = rows
        if not rows:
            unavailable.append({"section": name, "reason": "no_data"})
    return sections, unavailable


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
        return _run_tool(config, lambda: get_sleep(start, end), serialize_sleep)

    @mcp.tool()
    def health_hrv(start_date: str, end_date: str) -> dict[str, Any]:
        """Get HRV data for a date range (YYYY-MM-DD). Returns date, weekly_avg, last_night, status."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_hrv(start, end), serialize_hrv)

    @mcp.tool()
    def health_weight(start_date: str, end_date: str) -> dict[str, Any]:
        """Get weight data for a date range (YYYY-MM-DD). Returns date, weight_kg, bmi, body_fat_pct."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_weight(start, end), serialize_weight)

    @mcp.tool()
    def health_daily_summary(start_date: str, end_date: str) -> dict[str, Any]:
        """Get daily summary data for a date range (YYYY-MM-DD). Returns date, total_steps, distance_km, calories, floors, intensity minutes, and resting heart rate. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_daily_summary_range(start, end), serialize_daily_summary)

    @mcp.tool()
    def health_steps(start_date: str, end_date: str) -> dict[str, Any]:
        """Get steps data for a date range (YYYY-MM-DD). Returns date, total_steps, total_distance, step_goal."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_steps_range(start, end), serialize_steps)

    @mcp.tool()
    def health_intensity_minutes(start_date: str, end_date: str) -> dict[str, Any]:
        """Get intensity minutes for a date range (YYYY-MM-DD). Returns date, moderate_value, vigorous_value, weekly_goal."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_intensity_minutes_range(start, end), serialize_intensity_minutes)

    @mcp.tool()
    def health_body_battery(start_date: str, end_date: str) -> dict[str, Any]:
        """Get body battery for a date range (YYYY-MM-DD). Returns date, start_level, end_level. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_body_battery_range(start, end), serialize_body_battery)

    @mcp.tool()
    def health_stress(start_date: str, end_date: str) -> dict[str, Any]:
        """Get stress data for a date range (YYYY-MM-DD). Returns date, avg_stress, max_stress. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_stress_range(start, end), serialize_stress)

    @mcp.tool()
    def health_spo2(start_date: str, end_date: str) -> dict[str, Any]:
        """Get SpO2 data for a date range (YYYY-MM-DD). Returns date, avg_spo2, lowest_spo2. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_spo2_range(start, end), serialize_spo2)

    @mcp.tool()
    def health_resting_hr(start_date: str, end_date: str) -> dict[str, Any]:
        """Get resting heart rate for a date range (YYYY-MM-DD). Returns date, resting_hr. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_resting_hr_range(start, end), serialize_resting_hr)

    @mcp.tool()
    def health_readiness(start_date: str, end_date: str) -> dict[str, Any]:
        """Get training readiness for a date range (YYYY-MM-DD). Returns date, score, level. Note: large ranges may be slow (one API call per day)."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_training_readiness_range(start, end), serialize_training_readiness)

    @mcp.tool()
    def health_training_status(date: str) -> dict[str, Any]:
        """Get training status for a single date (YYYY-MM-DD). Returns date, training_status, load_type."""
        parsed = _parse_date(date, "date")
        return _run_tool(config, lambda: get_training_status(parsed), serialize_training_status)

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
        return _run_tool(
            config,
            lambda: list_activities(limit, start, activity_type, search, parsed_start, parsed_end),
            serialize_activity_summary,
        )

    @mcp.tool()
    def activity_get(activity_id: int, detail: bool = False) -> dict[str, Any]:
        """Get a single activity by ID. For multisport activities (triathlon etc.), includes child activities with per-sport details. Returns compact activity fields by default, or extended sport-aware metrics including running dynamics (GCT, vertical oscillation/ratio, stride length), cycling power suite (avg/max/normalized power, TSS, IF), swim aggregates (SWOLF, strokes), and training response (aerobic/anaerobic training effect, vO2max, recovery time) when detail=True. When detail=True, the response carries an additional ``unavailable`` array (when non-empty) annotating which registry-known metrics are not applicable to this sport (``not_applicable_to_sport``) or unexpectedly absent (``absent_in_response``)."""
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
        """Get weather for an activity. Returns temperature, weatherIconCode, windSpeed, windDirectionDegrees, humidity, precipProbability."""
        _validate_positive_id(activity_id, "activity_id")
        return _run_tool(config, lambda: get_activity_weather(activity_id), _weather_rows)

    @mcp.tool()
    def activity_laps(activity_id: int) -> dict[str, Any]:
        """Get lap-by-lap data for an activity. For pool-swim activities returns per-pool-length rows with SWOLF, stroke type, and stroke counts; for run/bike activities returns per-lap rows with HR, power (cycling), and running dynamics. For multisport parents (triathlon etc.), returns each child leg's laps concatenated with a 0-based ``leg_index`` stamped on every row."""
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

    # -- Workout tools ------------------------------------------------------

    @mcp.tool()
    def workout_list(limit: int = 20) -> dict[str, Any]:
        """List saved workouts. Returns id, name, sport, duration_min, description."""
        _validate_limit(limit)
        return _run_tool(config, lambda: list_workouts(limit), serialize_workout_summary)

    @mcp.tool()
    def workout_get(workout_id: int) -> dict[str, Any]:
        """Get workout detail by ID. Returns id, name, sport, duration_min, description, steps_summary, steps[]."""
        _validate_positive_id(workout_id, "workout_id")
        return _run_tool(config, lambda: get_workout(workout_id), serialize_workout_detail)

    @mcp.tool()
    def workout_calendar(start_date: str, end_date: str) -> dict[str, Any]:
        """Get scheduled workouts for a date range (YYYY-MM-DD). Returns date, id, name, type, duration_min, description."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(
            config, lambda: get_calendar_range(start, end),
            lambda raw: serialize_calendar_workout({"calendarItems": raw}),
        )

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
        base = WriteLogEvent(
            tool="workout_create",
            outcome="success",
            dry_run=dry_run,
            name_len=_workout_str_len(workout, "name"),
            description_len=_workout_str_len(workout, "description"),
        )
        with _write_audit(base) as audit:
            errors = validate_workout_input(workout, partial=False)
            if errors:
                audit.fail_validation(len(errors))
                return _validation_envelope(errors)

            payload = build_garmin_payload(workout)

            if dry_run:
                audit.dry_run()
                return _envelope([{
                    "ok": True,
                    "dry_run": True,
                    "wire_payload": payload,
                    "validation_report": {"ok": True},
                }])

            ensure_authenticated(config)
            raw = create_workout(payload)
            workout_id = _extract_workout_id(raw)
            audit.success(workout_id=workout_id)
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
        base = WriteLogEvent(tool="workout_schedule", outcome="success", workout_id=workout_id)
        with _write_audit(base) as audit:
            ensure_authenticated(config)
            raw = schedule_workout(workout_id, parsed_date)
            raw_dict = raw if isinstance(raw, dict) else {}
            audit.success()
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
        base = WriteLogEvent(
            tool="workout_update",
            outcome="success",
            dry_run=dry_run,
            workout_id=workout_id,
            name_len=_workout_str_len(workout, "name"),
            description_len=_workout_str_len(workout, "description"),
        )
        with _write_audit(base) as audit:
            errors = validate_workout_input(workout, partial=True)
            if errors:
                audit.fail_validation(len(errors))
                return _validation_envelope(errors)

            ensure_authenticated(config)
            existing = get_workout(workout_id)
            merged, warnings = merge_workout_payload(existing, workout)

            if dry_run:
                audit.dry_run()
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
            update_workout(workout_id, merged)
            audit.success()
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
        base = WriteLogEvent(tool="workout_delete", outcome="success", workout_id=workout_id)
        with _write_audit(base) as audit:
            ensure_authenticated(config)
            delete_workout(workout_id)
            audit.success()
            return _envelope([{
                "ok": True,
                "action": "deleted",
                "workout_id": workout_id,
            }])

    # -- Performance tools --------------------------------------------------

    @mcp.tool()
    def performance_race_predictions() -> dict[str, Any]:
        """Get latest race predictions. Returns race_type, predicted_time_seconds, distance_meters."""
        return _run_tool(config, get_race_predictions, serialize_race_predictions)

    @mcp.tool()
    def performance_endurance_score(start_date: str, end_date: str) -> dict[str, Any]:
        """Get endurance score for a date range (YYYY-MM-DD). Returns date, overall_score, endurance_classification."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_endurance_score_range(start, end), serialize_endurance_score)

    @mcp.tool()
    def performance_hill_score(start_date: str, end_date: str) -> dict[str, Any]:
        """Get hill score for a date range (YYYY-MM-DD). Returns date, overall_score, endurance_score, strength_score."""
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(config, lambda: get_hill_score_range(start, end), serialize_hill_score)

    @mcp.tool()
    def performance_thresholds() -> dict[str, Any]:
        """Get all available threshold metrics. Returns sport, lt_hr_bpm, lt_pace, ftp_watts, weight_kg."""
        return _run_tool(config, get_all_thresholds, serialize_thresholds)

    @mcp.tool()
    def performance_vo2max(date: str | None = None) -> dict[str, Any]:
        """Get VO2 max. Pass a date (YYYY-MM-DD) for a specific day, or omit for latest. Returns date, vo2max, sport."""

        def fetch() -> Any:
            if date is not None:
                return get_vo2max(_parse_date(date, "date"))
            return get_latest_vo2max()

        def serialize(raw: Any) -> list[dict[str, Any]]:
            rows = serialize_vo2max(raw)
            return rows if date is not None else select_latest_dated_rows(rows)

        return _run_tool(config, fetch, serialize)

    @mcp.tool()
    def performance_zones() -> dict[str, Any]:
        """Get lactate-threshold-derived zone inputs. Returns sport, lt_hr_bpm, lt_pace."""
        return _run_tool(config, get_lactate_threshold, serialize_zones)

    # -- Device tools -------------------------------------------------------

    @mcp.tool()
    def device_list() -> dict[str, Any]:
        """List registered Garmin devices. Returns device_id, display_name, device_type, last_sync_time."""
        return _run_tool(config, get_devices, serialize_device)

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

    def _calendar_rows(raw: Any) -> list[dict[str, Any]]:
        return serialize_calendar_workout({"calendarItems": raw})

    @mcp.tool()
    def report_snapshot(kind: str, date: str | None = None) -> dict[str, Any]:
        """Assemble a multi-section daily or weekly report in a single call, fanning out the underlying reads server-side.

        ``kind`` selects the report shape:
        - ``morning``: last night's ``sleep`` and ``hrv``, today's ``readiness`` and ``body_battery``, and today's ``planned_today`` workouts.
        - ``evening``: today's ``steps``, ``intensity_minutes``, ``stress``, ``body_battery``, completed ``activities_today``, and ``planned_tomorrow`` workouts.
        - ``weekly``: 7-day trends for ``sleep``, ``hrv``, ``stress``, ``steps``, ``resting_hr`` and ``body_battery``, the window's ``activities``, plus ``endurance_score`` and ``race_predictions``.

        ``date`` (YYYY-MM-DD) anchors the report and defaults to today; for ``weekly`` the window is the anchor day and the six preceding days. Returns ``{kind, date_range, sections, unavailable?}`` where ``sections`` maps each section name to its rows (same row shapes as the individual health/activity/performance/workout tools). A section with no data for the window is an empty list and is listed in ``unavailable`` with a ``reason`` (``not_found`` or ``no_data``); a section is never silently omitted. Auth, rate-limit, and server/network failures fail the whole call.
        """
        if kind not in ("morning", "evening", "weekly"):
            raise ToolError(f"kind must be one of: morning, evening, weekly (got '{kind}')")
        anchor = _parse_date(date, "date") if date is not None else date_cls.today()

        if kind == "morning":
            window_from = anchor
            specs: list[ReportSection] = [
                ("sleep", lambda: get_sleep(anchor, anchor), serialize_sleep),
                ("hrv", lambda: get_hrv(anchor, anchor), serialize_hrv),
                ("readiness", lambda: get_training_readiness_range(anchor, anchor), serialize_training_readiness),
                ("body_battery", lambda: get_body_battery_range(anchor, anchor), serialize_body_battery),
                ("planned_today", lambda: get_calendar_range(anchor, anchor), _calendar_rows),
            ]
        elif kind == "evening":
            window_from = anchor
            tomorrow = anchor + timedelta(days=1)
            specs = [
                ("steps", lambda: get_steps_range(anchor, anchor), serialize_steps),
                ("intensity_minutes", lambda: get_intensity_minutes_range(anchor, anchor), serialize_intensity_minutes),
                ("stress", lambda: get_stress_range(anchor, anchor), serialize_stress),
                ("body_battery", lambda: get_body_battery_range(anchor, anchor), serialize_body_battery),
                ("activities_today", lambda: list_activities(20, 0, None, None, anchor, anchor), serialize_activity_summary),
                ("planned_tomorrow", lambda: get_calendar_range(tomorrow, tomorrow), _calendar_rows),
            ]
        else:  # weekly
            window_from = anchor - timedelta(days=6)
            start = window_from
            specs = [
                ("sleep", lambda: get_sleep(start, anchor), serialize_sleep),
                ("hrv", lambda: get_hrv(start, anchor), serialize_hrv),
                ("stress", lambda: get_stress_range(start, anchor), serialize_stress),
                ("steps", lambda: get_steps_range(start, anchor), serialize_steps),
                ("resting_hr", lambda: get_resting_hr_range(start, anchor), serialize_resting_hr),
                ("body_battery", lambda: get_body_battery_range(start, anchor), serialize_body_battery),
                ("activities", lambda: list_activities(50, 0, None, None, start, anchor), serialize_activity_summary),
                ("endurance_score", lambda: get_endurance_score_range(start, anchor), serialize_endurance_score),
                ("race_predictions", get_race_predictions, serialize_race_predictions),
            ]

        def produce() -> dict[str, Any]:
            sections, unavailable = _collect_report_sections(specs)
            result: dict[str, Any] = {
                "kind": kind,
                "date_range": {"from": window_from.isoformat(), "to": anchor.isoformat()},
                "sections": sections,
            }
            if unavailable:
                result["unavailable"] = unavailable
            return result

        return _authenticated(config, produce)

    return mcp
