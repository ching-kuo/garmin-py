"""Bounded planned-versus-actual reads, shared by ``plan reconcile`` and MCP."""

from __future__ import annotations

from concurrent.futures import Future
from datetime import date
from typing import Any

from garmin_cli.date_utils import today
from garmin_cli.endpoints._base import _bounded_thread_pool, _cancel_futures_on_error
from garmin_cli.endpoints.activities import (
    get_activity,
    get_activity_details,
    get_activity_hr_in_timezones,
    get_activity_splits,
    list_activities,
)
from garmin_cli.endpoints.performance import get_power_zones
from garmin_cli.endpoints.workouts import get_calendar_range, get_workout
from garmin_cli.exceptions import GarminCliError
from garmin_cli.serializers import (
    serialize_activity_detail,
    serialize_activity_hr_zones,
    serialize_activity_laps,
    serialize_activity_summary,
    serialize_calendar_workout,
    serialize_detail_metrics,
    serialize_workout_detail,
    serialize_zones,
)
from garmin_cli.services.activities import downsample_rows
from garmin_cli.services.reconciliation import reconcile_plan
from garmin_cli.services.reconciliation_targets import (
    SUPPORTED_SPORTS,
    compare_activity_targets,
    power_zone_sport,
    required_stream_metrics,
)

TARGET_SAMPLE_BUDGET = 1000
TARGET_STREAM_LIMIT = 10
RECONCILE_MAX_DAYS = 28
RECONCILE_MAX_ACTIVITIES = 100


def validate_reconcile_inputs(
    start: date,
    end: date,
    max_activities: int,
    *,
    names: tuple[str, str, str] = ("start_date", "end_date", "max_activities"),
) -> None:
    """Raise ValueError for a range or activity cap the reconciliation refuses.

    *names* label the start, end and cap in messages (the CLI passes its flags).
    """
    start_name, end_name, max_name = names
    if start > end:
        raise ValueError(f"{start_name} must be on or before {end_name}")
    if (end - start).days + 1 > RECONCILE_MAX_DAYS:
        raise ValueError(f"reconciliation date range cannot exceed {RECONCILE_MAX_DAYS} days")
    if max_activities < 1 or max_activities > RECONCILE_MAX_ACTIVITIES:
        raise ValueError(f"{max_name} must be between 1 and {RECONCILE_MAX_ACTIVITIES}")


def _optional_target_read(call: Any) -> Any:
    """Treat target-detail 404s as missing sensor data, not tool failures."""
    try:
        return call()
    except GarminCliError as exc:
        if exc.error_code == "NOT_FOUND":
            return None
        raise


def _power_zones_or_none(sport: str) -> Any:
    """A transient power-zone read failure leaves power zone targets unresolved.

    Auth, rate-limit, and input errors still fail the call, like the other
    target reads; a 404 is already None.
    """
    try:
        return get_power_zones(sport)
    except GarminCliError as exc:
        if exc.error_code in {"SERVER_ERROR", "NETWORK_ERROR"}:
            return None
        raise


def collect_reconciliation(start: date, end: date, detail: str, max_activities: int) -> dict[str, Any]:
    """Compare scheduled workouts with completed activities in a validated range.

    Every examined activity is fetched in detail before exact matching,
    because the list response omits its Garmin workout association. The
    date/sport fallback is used only when it has exactly one candidate.
    """
    plan_today = today()
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
    power_zone_requests = 0
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
                today=plan_today,
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

            power_zone_sports = {
                activity_id: zone_sport
                for activity_id, (workout, _laps, _zones, sport) in target_inputs.items()
                if (zone_sport := power_zone_sport(workout, sport)) is not None
            }
            power_zone_futures = {
                zone_sport: pool.submit(_power_zones_or_none, zone_sport)
                for zone_sport in sorted(set(power_zone_sports.values()))
            }
            futures.extend(power_zone_futures.values())
            power_zone_requests = len(power_zone_futures)
            # Resolved before streams, so only a power zone with watt
            # bounds spends a stream slot.
            power_zone_rows = {
                zone_sport: serialize_zones({"power": future.result()})
                for zone_sport, future in power_zone_futures.items()
            }
            activity_power_zones = {
                activity_id: power_zone_rows[zone_sport]
                for activity_id, zone_sport in power_zone_sports.items()
            }

            stream_futures: dict[int, Future[Any]] = {}
            stream_blocked: set[int] = set()
            for activity_id, (workout, laps, _zones, _sport) in target_inputs.items():
                if not required_stream_metrics(workout, laps, activity_power_zones.get(activity_id)):
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
                    power_zones=activity_power_zones.get(activity_id),
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
        today=plan_today,
        target_comparisons=target_comparisons,
        stream_requests=stream_requests,
        power_zone_requests=power_zone_requests,
        sample_budget=TARGET_SAMPLE_BUDGET,
        stream_truncated=stream_truncated,
    )
