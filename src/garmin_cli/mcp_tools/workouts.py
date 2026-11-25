"""Workout MCP tools (list, get, calendar, create, schedule, update, delete, unschedule, send).

The generic write-audit machinery (``WriteLogEvent`` / ``_WriteAudit`` /
``_write_audit``) lives in :mod:`garmin_cli.mcp_tools._audit`; this module
keeps only its own ``_emit_write_log`` sink and workout-specific helpers.
"""
from __future__ import annotations

from typing import Any, cast

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from garmin_cli.auth import ensure_authenticated
from garmin_cli.config import CliConfig
from garmin_cli.endpoints.workouts import (
    create_workout,
    delete_workout,
    get_calendar_range,
    get_workout,
    list_workouts,
    send_workout_to_device,
    unschedule_workout,
    update_workout,
)
from garmin_cli.mcp_tools._audit import WriteLogEvent, _emit_audit, _write_audit
from garmin_cli.mcp_tools._shared import (
    StrictId,
    _envelope,
    _parse_date,
    _parse_date_range,
    _run_tool,
    _validate_limit,
    _validate_positive_id,
    _validation_envelope,
)
from garmin_cli.mcp_tools._inputs import WorkoutInput, WorkoutUpdate
from garmin_cli.mcp_tools._schemas import Envelope
from garmin_cli.serializers import (
    serialize_calendar_workout,
    serialize_workout_detail,
    serialize_workout_summary,
)
from garmin_cli.services.workouts import prepare_workout_send, schedule_workout_once
from garmin_cli.workout_builder import build_garmin_payload, merge_workout_payload
from garmin_cli.workout_schema import validate_workout_input

# Module-level so tests can patch the sink per domain.
_emit_write_log = _emit_audit


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

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def workout_list(limit: int = 20) -> Envelope:
        """List saved workouts. Returns id, name, sport, duration_min, description."""
        _validate_limit(limit)
        return _run_tool(config, lambda: list_workouts(limit), serialize_workout_summary)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def workout_get(workout_id: StrictId) -> Envelope:
        """Get workout detail by ID. Returns id, name, sport, duration_min, description, steps_summary, steps[]."""
        _validate_positive_id(workout_id, "workout_id")
        return _run_tool(config, lambda: get_workout(workout_id), serialize_workout_detail)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def workout_calendar(start_date: str, end_date: str) -> Envelope:
        """Get calendar items for a date range (YYYY-MM-DD).

        Returns scheduled workouts plus races/events. ``id`` remains the legacy
        calendar identifier; use ``workout_id`` to join a scheduled calendar
        item to a workout template and ``workout_schedule_id`` to unschedule it.
        """
        start, end = _parse_date_range(start_date, end_date)
        return _run_tool(
            config, lambda: get_calendar_range(start, end),
            lambda raw: serialize_calendar_workout({"calendarItems": raw}),
        )

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def workout_create(
        workout: WorkoutInput, dry_run: bool = False
    ) -> Envelope:
        """Create a workout (name 1-256 chars). Example step: {"type": "interval", "duration": {"type": "time", "value": 1800}, "target": {"type": "heart.rate.zone", "zone": 2}}.

        dry_run=true returns the Garmin payload without any Garmin call. Rule
        violations return a row ok=false, error_code INVALID_INPUT, errors[];
        success returns ok=true, action "created", workout_id.
        """
        data = cast(dict[str, Any], workout)
        base = WriteLogEvent(
            tool="workout_create",
            outcome="success",
            dry_run=dry_run,
            name_len=_workout_str_len(workout, "name"),
            description_len=_workout_str_len(workout, "description"),
        )
        with _write_audit(base, _emit_write_log) as audit:
            errors = validate_workout_input(data, partial=False)
            if errors:
                audit.fail_validation(len(errors))
                return _validation_envelope(errors)

            payload = build_garmin_payload(data)

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
    def workout_schedule(workout_id: StrictId, date: str, allow_multiple: bool = False) -> Envelope:
        """Schedule a saved workout on a date (YYYY-MM-DD). Destructive.

        Returns ok, action ("scheduled" or "no_op"), workout_id,
        workout_schedule_id (may be null), date. Refuses a date with another
        workout unless allow_multiple.
        """
        _validate_positive_id(workout_id, "workout_id")
        parsed_date = _parse_date(date, "date")
        base = WriteLogEvent(tool="workout_schedule", outcome="success", workout_id=workout_id)
        with _write_audit(base, _emit_write_log) as audit:
            ensure_authenticated(config)
            result = schedule_workout_once(workout_id, parsed_date, allow_multiple=allow_multiple)
            audit.success()
            return _envelope([{"ok": True, **result}])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def workout_update(
        workout_id: StrictId,
        workout: WorkoutUpdate,
        dry_run: bool = False,
    ) -> Envelope:
        """Update a workout: pass only the fields to change; the rest is kept.

        dry_run=true returns the merged payload after one Garmin read, without
        writing. Rule violations return ok=false, error_code INVALID_INPUT,
        errors[]; success returns ok=true, action "updated", workout_id.
        """
        _validate_positive_id(workout_id, "workout_id")
        data = cast(dict[str, Any], workout)
        base = WriteLogEvent(
            tool="workout_update",
            outcome="success",
            dry_run=dry_run,
            workout_id=workout_id,
            name_len=_workout_str_len(workout, "name"),
            description_len=_workout_str_len(workout, "description"),
        )
        with _write_audit(base, _emit_write_log) as audit:
            errors = validate_workout_input(data, partial=True)
            if errors:
                audit.fail_validation(len(errors))
                return _validation_envelope(errors)

            ensure_authenticated(config)
            existing = get_workout(workout_id)
            merged, warnings = merge_workout_payload(existing, data)

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

            update_workout(workout_id, merged)
            audit.success()
            return _envelope([{
                "ok": True,
                "action": "updated",
                "workout_id": workout_id,
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def workout_delete(workout_id: StrictId) -> Envelope:
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

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True, idempotent_hint=False))
    def workout_send_to_device(
        workout_id: StrictId, device_id: StrictId | None = None, dry_run: bool = False
    ) -> Envelope:
        """Send a saved workout to a watch or bike computer; it arrives on the device's next sync.

        device_id (from device_list) defaults to the only device that takes
        workouts of this workout's sport; when several qualify the error lists
        them. dry_run=true reads the workout and resolves the device without
        sending. Each send queues another copy. Returns ok, action "sent" (or
        dry_run true), workout_id, workout_name, device_id, display_name.
        """
        _validate_positive_id(workout_id, "workout_id")
        if device_id is not None:
            _validate_positive_id(device_id, "device_id")
        base = WriteLogEvent(
            tool="workout_send_to_device", outcome="success", dry_run=dry_run,
            workout_id=workout_id, device_id=device_id,
        )
        with _write_audit(base, _emit_write_log) as audit:
            ensure_authenticated(config)
            target = prepare_workout_send(workout_id, device_id)
            audit.set_base(device_id=target["device_id"])
            if dry_run:
                audit.dry_run()
                return _envelope([{"ok": True, "dry_run": True, **target}])
            send_workout_to_device(workout_id, target["workout_name"], target["device_id"])
            audit.success()
            return _envelope([{"ok": True, "action": "sent", **target}])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def workout_unschedule(schedule_id: StrictId) -> Envelope:
        """Remove a scheduled workout from the calendar by schedule ID.

        ``schedule_id`` is the ``workout_schedule_id`` returned by
        ``workout_schedule`` (also in ``workout_calendar``), not the workout ID.
        Destructive: the calendar entry is removed; the workout template is
        preserved. Returns ``ok: True, action: "unscheduled", schedule_id`` on
        success.
        """
        _validate_positive_id(schedule_id, "schedule_id")
        base = WriteLogEvent(
            tool="workout_unschedule", outcome="success", schedule_id=schedule_id
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
