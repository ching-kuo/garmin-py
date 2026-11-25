"""High-level, bounded MCP reads for AI coaching clients."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from garmin_cli.config import CliConfig
from garmin_cli.date_utils import today
from garmin_cli.mcp_tools._shared import _authenticated, _parse_date
from garmin_cli.services.coaching_snapshot import collect_snapshot, validate_snapshot_inputs
from garmin_cli.services.plan_reconcile import collect_reconciliation, validate_reconcile_inputs


def register_coaching_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register coaching orchestration reads without replacing primitives."""

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def coach_snapshot(
        date: str | None = None,
        baseline_days: int = 28,
        recent_daily_days: int = 9,
        include_extended_daily_baselines: bool = False,
        sports: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return bounded recovery, load, execution, and plan facts.

        Use when advising on training (recent days against baselines, load,
        upcoming plan); use report_snapshot for a fixed daily/weekly report.

        Baselines use prior calendar days only. The default 9-day daily window
        leaves slack over the 7-sample baseline minimum for days without data
        and is also the maximum ``recent_daily_days``.
        Default requests are bounded to 24 Garmin calls; a terminal rate limit
        preserves completed sections and returns ``complete=false`` and
        ``aborted=true``.
        """
        as_of = _parse_date(date, "date") if date is not None else None
        try:
            budget = validate_snapshot_inputs(baseline_days, recent_daily_days, include_extended_daily_baselines, sports)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return _authenticated(
            config,
            lambda: collect_snapshot(
                as_of if as_of is not None else today(),
                baseline_days,
                recent_daily_days,
                include_extended_daily_baselines,
                sports,
                budget,
            ),
        )

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def training_plan_reconcile(
        start_date: str,
        end_date: str,
        detail: Literal["summary", "targets"] = "summary",
        max_activities: int = 50,
    ) -> dict[str, Any]:
        """Compare scheduled workouts with completed activities in a bounded range.

        Every examined activity is fetched in detail before exact matching,
        because the list response omits its Garmin workout association. The
        date/sport fallback is used only when it has exactly one candidate.
        """
        start = _parse_date(start_date, "start_date")
        end = _parse_date(end_date, "end_date")
        try:
            validate_reconcile_inputs(start, end, max_activities)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return _authenticated(config, lambda: collect_reconciliation(start, end, detail, max_activities))
