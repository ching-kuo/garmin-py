"""High-level, bounded MCP reads for AI coaching clients."""

from __future__ import annotations

from concurrent.futures import Future
from datetime import date as Date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from garmin_cli.config import CliConfig
from garmin_cli.endpoints._base import _bounded_thread_pool, _cancel_futures_on_error
from garmin_cli.endpoints.activities import get_activity, list_activities
from garmin_cli.endpoints.workouts import get_calendar_range
from garmin_cli.mcp_tools._shared import _authenticated, _parse_date
from garmin_cli.serializers import (
    serialize_activity_detail,
    serialize_activity_summary,
    serialize_calendar_workout,
)
from garmin_cli.services.coaching_snapshot import collect_snapshot, validate_snapshot_inputs
from garmin_cli.services.reconciliation import reconcile_plan


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

        Baselines use prior calendar days only. The default 9-day daily window
        leaves slack over the 7-sample baseline minimum for days without data.
        Default requests are bounded to 30 Garmin calls; a terminal rate limit
        preserves completed sections and returns ``complete=false`` and
        ``aborted=true``.
        """
        as_of = _parse_date(date, "date") if date is not None else Date.today()
        try:
            budget = validate_snapshot_inputs(baseline_days, recent_daily_days, include_extended_daily_baselines, sports)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return _authenticated(
            config,
            lambda: collect_snapshot(
                as_of,
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
        detail: str = "summary",
        max_activities: int = 50,
    ) -> dict[str, Any]:
        """Compare scheduled workouts with completed activities in a bounded range.

        Every examined activity is fetched in detail before exact matching,
        because the list response omits its Garmin workout association. The
        date/sport fallback is used only when it has exactly one candidate.
        """
        start = _parse_date(start_date, "start_date")
        end = _parse_date(end_date, "end_date")
        if start > end:
            raise ToolError("start_date must be on or before end_date")
        if (end - start).days + 1 > 28:
            raise ToolError("reconciliation date range cannot exceed 28 days")
        if detail not in {"summary", "targets"}:
            raise ToolError("detail must be 'summary' or 'targets'")
        if max_activities < 1 or max_activities > 100:
            raise ToolError("max_activities must be between 1 and 100")

        def produce() -> dict[str, Any]:
            calendar_raw = get_calendar_range(start, end)
            calendar = serialize_calendar_workout({"calendarItems": calendar_raw})
            list_raw = list_activities(max_activities, 0, None, None, start, end)
            summaries = serialize_activity_summary(list_raw)
            activity_ids = [
                summary["id"]
                for summary in summaries
                if isinstance(summary.get("id"), int) and not isinstance(summary.get("id"), bool)
            ]
            # Summaries without a usable id cannot be detail-fetched; pass them
            # through so reconciliation surfaces them with a data-quality note
            # instead of silently dropping examined activities.
            detailed: list[dict[str, Any]] = [
                {**summary, "id": None}
                for summary in summaries
                if not (isinstance(summary.get("id"), int) and not isinstance(summary.get("id"), bool))
            ]
            if activity_ids:
                # Bounded fan-out with deterministic (submission) order; the
                # first failing fetch cancels the pending ones before raising.
                futures: list[Future[Any]] = []
                with _bounded_thread_pool(len(activity_ids)) as pool, _cancel_futures_on_error(futures):
                    futures.extend(pool.submit(get_activity, activity_id) for activity_id in activity_ids)
                    for future in futures:
                        rows = serialize_activity_detail(future.result())
                        if rows:
                            detailed.append(rows[0])
            return reconcile_plan(
                calendar,
                detailed,
                start_date=start,
                end_date=end,
                detail=detail,
                activities_examined=len(summaries),
                detail_requests=len(activity_ids),
                max_activities=max_activities,
                truncated=len(summaries) >= max_activities,
            )

        return _authenticated(config, produce)
