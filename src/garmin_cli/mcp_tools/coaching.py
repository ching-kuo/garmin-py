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
from garmin_cli.endpoints.activities import (
    get_activity,
    get_activity_details,
    get_activity_hr_in_timezones,
    get_activity_splits,
    list_activities,
)
from garmin_cli.endpoints.workouts import get_calendar_range, get_workout
from garmin_cli.exceptions import GarminCliError
from garmin_cli.mcp_tools._shared import _authenticated, _parse_date
from garmin_cli.serializers import (
    serialize_activity_detail,
    serialize_activity_hr_zones,
    serialize_activity_laps,
    serialize_activity_summary,
    serialize_calendar_workout,
    serialize_detail_metrics,
    serialize_workout_detail,
)
from garmin_cli.services.activities import downsample_rows
from garmin_cli.services.coaching_snapshot import collect_snapshot, validate_snapshot_inputs
from garmin_cli.services.reconciliation import reconcile_plan
from garmin_cli.services.reconciliation_targets import (
    SUPPORTED_SPORTS,
    compare_activity_targets,
    required_stream_metrics,
)

TARGET_SAMPLE_BUDGET = 1000
TARGET_STREAM_LIMIT = 10


def _optional_target_read(call: Any) -> Any:
    """Treat target-detail 404s as missing sensor data, not tool failures."""
    try:
        return call()
    except GarminCliError as exc:
        if exc.error_code == "NOT_FOUND":
            return None
        raise


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
            activity_raw: dict[int, dict[str, Any]] = {}
            target_comparisons: dict[int, dict[str, Any]] = {}
            stream_requests = 0
            stream_truncated = False
            futures: list[Future[Any]] = []
            task_count = max(1, len(activity_ids) * 4)
            with _bounded_thread_pool(task_count) as pool, _cancel_futures_on_error(futures):
                detail_futures = {
                    activity_id: pool.submit(get_activity, activity_id)
                    for activity_id in activity_ids
                }
                futures.extend(detail_futures.values())
                for activity_id in activity_ids:
                    raw = detail_futures[activity_id].result()
                    activity_raw[activity_id] = raw
                    rows = serialize_activity_detail(raw)
                    if rows:
                        detailed.append(rows[0])

                if detail == "targets":
                    # The summary pass is recomputed here (cheap, pure CPU) to
                    # learn which rows matched before the targets fan-out.
                    summary_result = reconcile_plan(
                        calendar,
                        detailed,
                        start_date=start,
                        end_date=end,
                        detail="summary",
                        activities_examined=len(summaries),
                        detail_requests=len(activity_ids),
                        max_activities=max_activities,
                        truncated=len(summaries) >= max_activities,
                    )
                    matched = [
                        row
                        for row in summary_result["entries"]
                        if row["state"] in {"completed_exact", "completed_inferred", "completed_modified"}
                        and row["planned"] is not None
                        and row["actual"] is not None
                    ]
                    supported = [
                        row for row in matched if row["actual"].get("sport") in SUPPORTED_SPORTS
                    ]
                    workout_futures = {
                        workout_id: pool.submit(
                            _optional_target_read,
                            lambda workout_id=workout_id: get_workout(workout_id),
                        )
                        for workout_id in dict.fromkeys(
                            row["planned"]["workout_id"] for row in supported
                        )
                    }
                    lap_futures = {
                        row["actual"]["activity_id"]: pool.submit(
                            _optional_target_read,
                            lambda activity_id=row["actual"]["activity_id"]: get_activity_splits(
                                activity_id
                            ),
                        )
                        for row in supported
                    }
                    zone_futures = {
                        row["actual"]["activity_id"]: pool.submit(
                            _optional_target_read,
                            lambda activity_id=row["actual"]["activity_id"]:
                            get_activity_hr_in_timezones(activity_id),
                        )
                        for row in supported
                    }
                    futures.extend(workout_futures.values())
                    futures.extend(lap_futures.values())
                    futures.extend(zone_futures.values())

                    target_inputs: dict[int, tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], Any]] = {}
                    for row in matched:
                        activity_id = row["actual"]["activity_id"]
                        sport = row["actual"].get("sport")
                        if sport not in SUPPORTED_SPORTS:
                            target_comparisons[activity_id] = compare_activity_targets(
                                sport=sport,
                                workout={},
                                laps=[],
                                hr_zones=[],
                                samples=[],
                            )
                            continue
                        workout_raw = workout_futures[row["planned"]["workout_id"]].result() or {}
                        workout_rows = serialize_workout_detail(workout_raw)
                        workout = workout_rows[0] if workout_rows else {}
                        splits = lap_futures[activity_id].result() or {}
                        laps = serialize_activity_laps(
                            activity_raw.get(activity_id, {}),
                            splits,
                        )
                        zones = serialize_activity_hr_zones(
                            zone_futures[activity_id].result() or []
                        )
                        target_inputs[activity_id] = (workout, laps, zones, sport)

                    stream_futures: dict[int, Future[Any]] = {}
                    stream_blocked: set[int] = set()
                    for activity_id, (workout, laps, _zones, _sport) in target_inputs.items():
                        if not required_stream_metrics(workout, laps):
                            continue
                        if len(stream_futures) >= TARGET_STREAM_LIMIT:
                            stream_truncated = True
                            stream_blocked.add(activity_id)
                            continue
                        stream_futures[activity_id] = pool.submit(
                            _optional_target_read,
                            lambda activity_id=activity_id: get_activity_details(activity_id),
                        )
                    futures.extend(stream_futures.values())
                    stream_requests = len(stream_futures)

                    for activity_id, (workout, laps, zones, sport) in target_inputs.items():
                        samples: list[dict[str, Any]] = []
                        unavailable_reason = None
                        if activity_id in stream_futures:
                            stream_raw = stream_futures[activity_id].result()
                            if stream_raw:
                                all_samples = serialize_detail_metrics(stream_raw)
                                samples, _stride = downsample_rows(
                                    all_samples,
                                    TARGET_SAMPLE_BUDGET,
                                )
                            else:
                                unavailable_reason = "missing_metric_stream"
                        elif activity_id in stream_blocked:
                            unavailable_reason = "stream_request_limit_reached"
                        target_comparisons[activity_id] = compare_activity_targets(
                            sport=sport,
                            workout=workout,
                            laps=laps,
                            hr_zones=zones,
                            samples=samples,
                            stream_unavailable_reason=unavailable_reason,
                        )
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
                target_comparisons=target_comparisons,
                stream_requests=stream_requests,
                sample_budget=TARGET_SAMPLE_BUDGET,
                stream_truncated=stream_truncated,
            )

        return _authenticated(config, produce)
