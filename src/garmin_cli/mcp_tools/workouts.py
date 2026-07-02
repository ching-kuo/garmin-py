"""Workout MCP tools (list, get, calendar, create, schedule, update, delete).

The generic write-audit machinery (``WriteLogEvent`` / ``_WriteAudit`` /
``_write_audit``) lives in :mod:`garmin_cli.mcp_tools._shared`; this module
keeps only its own ``_emit_write_log`` sink and workout-specific helpers.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from garmin_cli.auth import ensure_authenticated
from garmin_cli.config import CliConfig
from garmin_cli.endpoints.workouts import (
    create_workout,
    delete_workout,
    get_calendar_range,
    get_workout,
    list_workouts,
    schedule_workout,
    unschedule_workout,
    update_workout,
)
from garmin_cli.mcp_tools._shared import (
    WriteLogEvent,
    _envelope,
    _parse_date,
    _parse_date_range,
    _run_tool,
    _validate_limit,
    _validate_positive_id,
    _validation_envelope,
    _write_audit,
)
from garmin_cli.serializers import (
    serialize_calendar_workout,
    serialize_workout_detail,
    serialize_workout_summary,
)
from garmin_cli.workout_builder import build_garmin_payload, merge_workout_payload
from garmin_cli.workout_schema import validate_workout_input

_logger = logging.getLogger(__name__)


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


def register_workout_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register the workout read and write tools on ``mcp``."""

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
        with _write_audit(base, _emit_write_log) as audit:
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
        with _write_audit(base, _emit_write_log) as audit:
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
        with _write_audit(base, _emit_write_log) as audit:
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
        with _write_audit(base, _emit_write_log) as audit:
            ensure_authenticated(config)
            delete_workout(workout_id)
            audit.success()
            return _envelope([{
                "ok": True,
                "action": "deleted",
                "workout_id": workout_id,
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def workout_unschedule(schedule_id: int) -> dict[str, Any]:
        """Remove a scheduled workout from the calendar by schedule ID.

        ``schedule_id`` is the ``workout_schedule_id`` returned by
        ``workout_schedule`` (also in ``workout_calendar``), not the workout ID.
        Destructive: the calendar entry is removed; the workout template is
        preserved. Returns ``ok: True, action: "unscheduled", schedule_id`` on
        success.
        """
        _validate_positive_id(schedule_id, "schedule_id")
        base = WriteLogEvent(
            tool="workout_unschedule", outcome="success", workout_id=schedule_id
        )
        with _write_audit(base, _emit_write_log) as audit:
            ensure_authenticated(config)
            unschedule_workout(schedule_id)
            audit.success()
            return _envelope([{
                "ok": True,
                "action": "unscheduled",
                "schedule_id": schedule_id,
            }])
