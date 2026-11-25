"""Stateless preview and destructive application of structured training plans.

The orchestration lives in :mod:`garmin_cli.services.plan_apply`; this module
handles arguments, authentication, and write auditing.
"""

from __future__ import annotations

from typing import Any, cast

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from garmin_cli.auth import ensure_authenticated
from garmin_cli.config import CliConfig
from garmin_cli.mcp_tools._inputs import TrainingPlan
from garmin_cli.mcp_tools._audit import WriteLogEvent, _emit_audit, _write_audit
from garmin_cli.mcp_tools._shared import StrictId, _authenticated, _parse_date, _validate_positive_id
from garmin_cli.services.plan_apply import apply_training_plan, calendar_with_projections, plan_dates
from garmin_cli.services.plan_reschedule import reschedule_schedule
from garmin_cli.services.plan_results import invalid_plan_result
from garmin_cli.services.training_plan import preview_training_plan, validate_training_plan

# Module-level so tests can patch the sink per domain.
_emit_write_log = _emit_audit


def register_training_plan_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register state-free plan preview, apply, and source-verified moves."""

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def training_plan_preview(plan: TrainingPlan) -> dict[str, Any]:
        """Read live state and return a normalized plan diff without writing."""
        data = cast(dict[str, Any], plan)
        errors = validate_training_plan(data)
        if errors:
            return invalid_plan_result(errors)
        start, end = plan_dates(data)
        return _authenticated(
            config,
            lambda: preview_training_plan(data, *calendar_with_projections(start, end)),
        )

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def training_plan_apply(plan: TrainingPlan) -> dict[str, Any]:
        """Apply a validated plan after live rechecks; no confirmation boolean is accepted."""
        data = cast(dict[str, Any], plan)
        base = WriteLogEvent(tool="training_plan_apply", outcome="success", name_len=len(data["name"]))
        with _write_audit(base, _emit_write_log) as audit:
            errors = validate_training_plan(data)
            if errors:
                audit.fail_validation(len(errors))
                return invalid_plan_result(errors)
            ensure_authenticated(config)
            return audit.plan_result(apply_training_plan(data))

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def training_plan_reschedule(schedule_id: StrictId, new_date: str, expected_date: str) -> dict[str, Any]:
        """Move a known schedule destination-first, then remove its source.

        ``expected_date`` is required because Garmin exposes no direct lookup by
        schedule ID; it lets the tool verify that the source was not changed.
        A new date that already holds a different workout returns a
        ``destination_occupied`` conflict without writing.
        """
        _validate_positive_id(schedule_id, "schedule_id")
        destination = _parse_date(new_date, "new_date")
        _parse_date(expected_date, "expected_date")
        base = WriteLogEvent(tool="training_plan_reschedule", outcome="success", schedule_id=schedule_id)
        with _write_audit(base, _emit_write_log) as audit:
            ensure_authenticated(config)
            return audit.plan_result(reschedule_schedule(schedule_id, destination, expected_date))
