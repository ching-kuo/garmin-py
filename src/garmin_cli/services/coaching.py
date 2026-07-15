"""Pure aggregation primitives for the AI-coach snapshot surface.

The transport/front-end layers fetch and serialize Garmin payloads before they
reach this module. Keeping aggregation here deterministic makes its data
quality and provenance contracts testable without an authenticated account.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import median
from typing import Any

_MIN_BASELINE_SAMPLES = 7


def coach_snapshot_request_budget(
    baseline_days: int,
    recent_daily_days: int,
    include_extended_daily_baselines: bool,
) -> int:
    """Return the number of Garmin requests in a non-paginated snapshot.

    Five range endpoints, one activity list, readiness, SpO2, training status,
    and calendar are single requests. Resting HR and stress are daily endpoints
    and therefore account for two requests per prior-day window plus current.
    """
    daily_days = baseline_days if include_extended_daily_baselines else recent_daily_days
    return 10 + 2 * (daily_days + 1)


def _row_date(row: dict[str, Any]) -> date | None:
    value = row.get("date")
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _finite_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # NaN/infinite values must not poison medians or sums.
    return value if math.isfinite(value) else None


def _current_value(rows: list[dict[str, Any]], key: str, as_of: date) -> tuple[float | int | None, str | None, bool]:
    dated = [(row, _row_date(row)) for row in rows]
    dated.sort(key=lambda item: item[1] or date.min, reverse=True)
    for row, row_date in dated:
        value = _finite_number(row.get(key))
        if value is not None and row_date is not None and row_date <= as_of:
            return value, row_date.isoformat(), row_date < as_of
    return None, None, False


def _signal(
    name: str,
    baseline_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    key: str,
    as_of: date,
    baseline_start: date,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    observations = [
        value
        for row in baseline_rows
        if (row_date := _row_date(row)) is not None and baseline_start <= row_date < as_of
        if (value := _finite_number(row.get(key))) is not None
    ]
    current, current_date, stale = _current_value(current_rows, key, as_of)
    result: dict[str, Any] = {
        "signal": name,
        "source_field": key,
        "sample_count": len(observations),
        "minimum_samples": _MIN_BASELINE_SAMPLES,
        "baseline_from": baseline_start.isoformat(),
        "baseline_to": (as_of - timedelta(days=1)).isoformat(),
        "current_value": current,
        "current_value_date": current_date,
        "baseline_median": None,
        "absolute_delta": None,
        "percentage_delta": None,
        "state": "ok",
    }
    if current is None:
        result["state"] = "missing_current"
        return result, {"section": f"recovery.{name}", "reason": "missing_current"}
    if stale:
        result["state"] = "stale_current"
        return result, {"section": f"recovery.{name}", "reason": "stale_current"}
    if len(observations) < _MIN_BASELINE_SAMPLES:
        result["state"] = "insufficient_samples"
        return result, {"section": f"recovery.{name}", "reason": "insufficient_samples"}
    baseline = median(observations)
    result["baseline_median"] = baseline
    result["absolute_delta"] = current - baseline
    if baseline != 0:
        result["percentage_delta"] = (current - baseline) / baseline * 100
    return result, None


def _activity_rows(rows: list[dict[str, Any]], as_of: date, sports: list[str] | None) -> list[dict[str, Any]]:
    wanted = set(sports or [])
    return [
        row
        for row in rows
        if (row_date := _row_date(row)) is not None and row_date <= as_of and (not wanted or row.get("type") in wanted)
    ]


def aggregate_activity_load(
    rows: list[dict[str, Any]], as_of: date, sports: list[str] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Aggregate activity-level load by ISO week and sport without judgments."""
    activities = _activity_rows(rows, as_of, sports)
    weekly: dict[tuple[date, str | None], dict[str, Any]] = {}
    by_sport: dict[str | None, dict[str, Any]] = {}
    for row in activities:
        row_date = _row_date(row)
        assert row_date is not None
        iso = row_date.isocalendar()
        week_start = date.fromisocalendar(iso.year, iso.week, 1)
        sport = row.get("type") if isinstance(row.get("type"), str) else None
        bucket = weekly.setdefault(
            (week_start, sport),
            {
                "week_start": week_start.isoformat(),
                "sport": sport,
                "activity_count": 0,
                "duration_min": 0,
                "distance_km": 0,
                "training_load": 0,
                "null_training_load_count": 0,
            },
        )
        all_time = by_sport.setdefault(
            sport,
            {
                "sport": sport,
                "activity_count": 0,
                "duration_min": 0,
                "distance_km": 0,
                "training_load": 0,
                "null_training_load_count": 0,
            },
        )
        for summary in (bucket, all_time):
            summary["activity_count"] += 1
            summary["duration_min"] += _finite_number(row.get("duration_min")) or 0
            summary["distance_km"] += _finite_number(row.get("distance_km")) or 0
            training_load = _finite_number(row.get("training_load"))
            if training_load is None:
                summary["null_training_load_count"] += 1
            else:
                summary["training_load"] += training_load
    execution = {
        "activity_count": len(activities),
        "duration_min": sum(_finite_number(row.get("duration_min")) or 0 for row in activities),
        "distance_km": sum(_finite_number(row.get("distance_km")) or 0 for row in activities),
    }
    weekly_rows = sorted(weekly.values(), key=lambda row: (row["week_start"], row["sport"] or ""))
    sport_rows = sorted(by_sport.values(), key=lambda row: row["sport"] or "")
    return weekly_rows, sport_rows, execution


def build_coach_snapshot(
    *,
    as_of: date,
    baseline_days: int,
    daily_baseline_days: int,
    sections: dict[str, list[dict[str, Any]]],
    unavailable: list[dict[str, str]],
    errors: list[dict[str, Any]],
    complete: bool,
    aborted: bool,
    estimated_requests: int,
    completed_requests: int,
    sports: list[str] | None,
) -> dict[str, Any]:
    """Construct a deterministic, source-attributed coaching snapshot."""
    baseline_start = as_of - timedelta(days=baseline_days)
    # Resting HR and stress are per-day endpoints fetched only over the shorter
    # daily window, so their reported baseline must not claim the full range.
    daily_start = as_of - timedelta(days=daily_baseline_days)
    signal_specs = (
        ("hrv", "hrv", "last_night", baseline_start),
        ("sleep_duration", "sleep", "duration_hours", baseline_start),
        ("sleep_score", "sleep", "score", baseline_start),
        ("resting_heart_rate", "resting_hr", "resting_hr", daily_start),
        ("stress", "stress", "avg_stress", daily_start),
        ("body_battery_peak", "body_battery", "max_level", baseline_start),
    )
    signals: list[dict[str, Any]] = []
    quality: list[dict[str, str]] = []
    for name, section, key, signal_baseline_start in signal_specs:
        current_section = f"current_{section}"
        signal, issue = _signal(
            name,
            sections.get(section, []),
            sections.get(current_section, sections.get(section, [])),
            key,
            as_of,
            signal_baseline_start,
        )
        signals.append(signal)
        if issue:
            quality.append(issue)

    activities = _activity_rows(sections.get("activities", []), as_of, sports)
    weekly_load, by_sport, execution_summary = aggregate_activity_load(activities, as_of, sports)
    activities.sort(key=lambda row: (row.get("date") or "", row.get("id") or 0), reverse=True)
    calendar = sections.get("calendar", [])
    next_end = as_of + timedelta(days=6)
    plan_rows = [row for row in calendar if _row_date(row) is not None]
    next_7_days = [row for row in plan_rows if (row_date := _row_date(row)) is not None and as_of <= row_date <= next_end]
    plan = {
        "today": [row for row in plan_rows if _row_date(row) == as_of],
        "next_7_days": next_7_days,
        "target_events": [row for row in plan_rows if row.get("is_race") is True or row.get("primary_event") is True],
    }
    current_status_rows = sections.get("training_status", [])
    return {
        "complete": complete,
        "aborted": aborted,
        "as_of": as_of.isoformat(),
        "baseline": {
            "from": baseline_start.isoformat(),
            "to": (as_of - timedelta(days=1)).isoformat(),
            "days": baseline_days,
        },
        "recovery": {"signals": signals},
        "load": {
            "current_status": current_status_rows[0] if current_status_rows else {},
            "weekly_activity_load": weekly_load,
            "by_sport": by_sport,
        },
        "plan": plan,
        "wellness": {
            "training_readiness": sections.get("training_readiness", []),
            "spo2": sections.get("spo2", []),
            "steps": sections.get("steps", []),
            "weight": sections.get("weight", []),
        },
        "execution": {"recent_activities": activities[:20], "summary": execution_summary},
        "data_quality": quality,
        "unavailable": unavailable,
        "errors": errors,
        "provenance": {
            "estimated_requests": estimated_requests,
            "completed_requests": completed_requests,
            "truncated": len(sections.get("activities", [])) >= 100,
        },
    }
