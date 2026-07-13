"""Miscellaneous MCP tools: device list, login status, and report_snapshot.

``report_snapshot`` fans out reads across several domains, so this module binds
its own references to the health / activity / workout / metrics endpoints it
composes. Those bindings are independent of the per-domain tool modules: tests
patch ``garmin_cli.mcp_tools.misc.*`` for snapshot behavior.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from garmin_cli import backend as garth
from garmin_cli.auth import _probe_session, _secure_directory, complete_mfa_login
from garmin_cli.config import CliConfig
from garmin_cli.endpoints.activities import list_activities
from garmin_cli.endpoints.devices import get_devices
from garmin_cli.endpoints.health import (
    get_body_battery_range,
    get_hrv,
    get_intensity_minutes_range,
    get_resting_hr_range,
    get_sleep,
    get_steps_range,
    get_stress_range,
    get_training_readiness_range,
)
from garmin_cli.endpoints.metrics import get_endurance_score_range, get_race_predictions
from garmin_cli.endpoints.workouts import get_calendar_range
from garmin_cli.exceptions import GarminCliError, extract_status_code
from garmin_cli.mcp_tools._shared import (
    ReportSection,
    _authenticated,
    _collect_report_sections,
    _handle_error,
    _parse_date,
    _run_tool,
)
from garmin_cli.serializers import (
    serialize_activity_summary,
    serialize_body_battery,
    serialize_calendar_workout,
    serialize_device,
    serialize_endurance_score,
    serialize_hrv,
    serialize_intensity_minutes,
    serialize_race_predictions,
    serialize_resting_hr,
    serialize_sleep,
    serialize_steps,
    serialize_stress,
    serialize_training_readiness,
)

# Alias so report_snapshot, whose user-facing parameter is named ``date``, can
# still reach ``date.today()`` without the parameter shadowing the class.
date_cls = date


def _calendar_rows(raw: Any) -> list[dict[str, Any]]:
    return serialize_calendar_workout({"calendarItems": raw})


def register_misc_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register device, login-status, and report_snapshot tools on ``mcp``."""

    @mcp.tool()
    def device_list() -> dict[str, Any]:
        """List registered Garmin devices. Returns device_id, display_name, device_type, last_sync_time."""
        return _run_tool(config, get_devices, serialize_device)

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

    @mcp.tool()
    def submit_mfa_code(mfa_code: str) -> dict[str, Any]:
        """Complete a Garmin login that failed with MFA_REQUIRED.

        When any tool reports that Garmin requires a multi-factor
        authentication code, ask the user for the one-time code Garmin sent
        them (email, SMS, or authenticator app) and submit it here. On success
        the session is saved and all other tools work without logging in
        again. Codes are single-use: if verification fails, retry the original
        tool call to trigger a fresh code before submitting a new one.
        """
        code = mfa_code.strip()
        if not code:
            raise ToolError("mfa_code must be a non-empty string")
        try:
            complete_mfa_login(config, code)
        except GarminCliError as exc:
            raise _handle_error(exc) from exc
        return {"authenticated": True, "garmin_home": os.path.expanduser(config.garth_home)}

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
