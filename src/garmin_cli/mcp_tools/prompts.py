"""Content-only MCP prompts for common Garmin coaching workflows."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer


def register_prompts(mcp: MCPServer) -> None:
    """Register the four stable coaching workflow prompts."""

    @mcp.prompt()
    def weekly_training_review(date: str | None = None) -> str:
        """Review the latest seven days of training and recovery."""
        anchor = date or "today"
        return (
            f"Prepare a weekly training review ending on {anchor}. Call "
            "`coach_snapshot` for recovery and load context, then call "
            "`training_plan_reconcile` with detail=\"summary\" for the seven-day "
            "window. Separate observed facts from interpretation; note missing "
            "data and request provenance before suggesting adjustments."
        )

    @mcp.prompt()
    def recovery_check(date: str | None = None) -> str:
        """Run a morning readiness debrief."""
        anchor = date or "today"
        return (
            f"Run a morning recovery check for {anchor} with `coach_snapshot`. "
            "Summarize sleep, HRV, resting heart rate, stress, body battery, "
            "readiness, and today's planned session. Treat missing or stale "
            "signals as uncertainty, not as negative evidence."
        )

    @mcp.prompt()
    def compare_recent_activities(activity_type: str = "running") -> str:
        """Compare two recent activities of the same type."""
        return (
            f"Use `activity_list` to find two recent {activity_type} sessions "
            "that are similar in purpose or duration. Fetch each with "
            "`activity_get` using detail=true. Compare pace/speed, heart rate, "
            "power or cadence where applicable, training response, and data "
            "quality. Explain material context differences before conclusions."
        )

    @mcp.prompt()
    def plan_next_week(week_start: str | None = None) -> str:
        """Guide a preview-first training-plan workflow."""
        anchor = week_start or "the next calendar week"
        return (
            f"Build a proposed plan for {anchor}. Use `coach_snapshot` and "
            "`training_plan_reconcile` for current context, construct the plan, "
            "and call `training_plan_preview` first. Present the live diff and "
            "validation results. `training_plan_apply` is destructive: call it "
            "only after explicit human confirmation of the exact preview."
        )
