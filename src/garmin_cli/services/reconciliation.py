"""Deterministic planned-versus-actual matching for coaching clients."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any


def _date_part(value: Any) -> str | None:
    return value[:10] if isinstance(value, str) and len(value) >= 10 else None


def _actual_summary(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_id": activity.get("id"),
        "date": _date_part(activity.get("date")),
        "sport": activity.get("type"),
        "duration_min": activity.get("duration_min"),
        "distance_km": activity.get("distance_km"),
        "training_load": activity.get("training_load"),
        "aerobic_training_effect": activity.get("aerobic_training_effect"),
        "anaerobic_training_effect": activity.get("anaerobic_training_effect"),
        "workout_id": activity.get("workout_id"),
    }


def _planned_summary(calendar: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": calendar.get("date"),
        "workout_id": calendar.get("workout_id"),
        "workout_schedule_id": calendar.get("workout_schedule_id"),
        "sport": calendar.get("type"),
        "duration_min": calendar.get("duration_min"),
        "name": calendar.get("name"),
    }


def reconcile_plan(
    calendar_rows: list[dict[str, Any]],
    activity_rows: list[dict[str, Any]],
    *,
    start_date: date,
    end_date: date,
    detail: str,
    activities_examined: int,
    detail_requests: int,
    max_activities: int,
    truncated: bool,
    today: date | None = None,
) -> dict[str, Any]:
    """Match scheduled calendar workouts to fully fetched activity details.

    Exact workout association is evaluated before any date/sport heuristic.
    The heuristic only resolves a one-to-one candidate and otherwise leaves the
    plan explicit as ambiguous. No decision is persisted across calls.
    """
    today = today or date.today()
    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()
    scheduled = [
        row
        for row in calendar_rows
        if row.get("workout_id") is not None
        and isinstance(row.get("date"), str)
        and start_iso <= row["date"] <= end_iso
    ]
    in_range = [
        row
        for row in activity_rows
        if (row_date := _date_part(row.get("date"))) is not None and start_iso <= row_date <= end_iso
    ]
    # An activity without an id has no usable match identity; matching one
    # would poison the matched-id set for every other id-less activity.
    activities = [row for row in in_range if row.get("id") is not None]
    unidentified = [row for row in in_range if row.get("id") is None]
    occurrences = Counter(row.get("workout_id") for row in scheduled)
    matched_activity_ids: set[Any] = set()
    entries: list[dict[str, Any]] = []

    for calendar in sorted(scheduled, key=lambda row: (row.get("date") or "", row.get("workout_id") or 0)):
        planned = _planned_summary(calendar)
        row: dict[str, Any] = {
            "planned": planned,
            "actual": None,
            "state": None,
            "match_method": None,
            "match_confidence": None,
            "data_quality": [],
        }
        exact = [
            activity
            for activity in activities
            if activity.get("id") not in matched_activity_ids
            if activity.get("workout_id") == calendar.get("workout_id")
        ]
        same_date_exact = [activity for activity in exact if _date_part(activity.get("date")) == calendar.get("date")]
        if len(same_date_exact) == 1:
            exact = same_date_exact
        elif not same_date_exact and exact and occurrences[calendar.get("workout_id")] > 1:
            # The template is scheduled on several dates; a cross-date exact
            # activity cannot be attributed to this occurrence in particular.
            row["data_quality"].append({"reason": "cross_date_exact_ambiguous"})
            exact = []
        if len(exact) == 1:
            activity = exact[0]
            matched_activity_ids.add(activity.get("id"))
            row.update(
                {
                    "actual": _actual_summary(activity),
                    "state": "completed_exact",
                    "match_method": "workout_id",
                    "match_confidence": "exact",
                }
            )
        elif len(exact) > 1:
            row.update(
                {
                    "state": "ambiguous",
                    "match_method": "workout_id",
                    "match_confidence": "ambiguous",
                    "data_quality": [{"reason": "multiple_exact_activities"}],
                }
            )
        else:
            candidates = [
                activity
                for activity in activities
                if activity.get("id") not in matched_activity_ids
                and _date_part(activity.get("date")) == calendar.get("date")
                and activity.get("type") == calendar.get("type")
                # An activity carrying a different workout association belongs
                # to that workout; the heuristic must not steal it.
                and activity.get("workout_id") is None
            ]
            if len(candidates) == 1:
                activity = candidates[0]
                matched_activity_ids.add(activity.get("id"))
                row.update(
                    {
                        "actual": _actual_summary(activity),
                        "state": "completed_inferred",
                        "match_method": "date_and_sport",
                        "match_confidence": "inferred",
                    }
                )
            elif len(candidates) > 1:
                row.update(
                    {
                        "state": "ambiguous",
                        "match_method": None,
                        "match_confidence": "ambiguous",
                        "data_quality": [{"reason": "multiple_date_sport_candidates"}],
                    }
                )
            elif date.fromisoformat(calendar["date"]) >= today:
                # Today's workout stays planned until the day has passed.
                row.update({"state": "planned_future", "match_method": None, "match_confidence": None})
            else:
                row.update({"state": "skipped", "match_method": None, "match_confidence": None})
        if detail == "targets" and row["actual"] is not None:
            row["target_comparison"] = {
                "state": "insufficient_data",
                "reason": "target stream analysis is unavailable for this activity",
            }
        entries.append(row)

    for activity in activities:
        if activity.get("id") in matched_activity_ids:
            continue
        entries.append(
            {
                "planned": None,
                "actual": _actual_summary(activity),
                "state": "unplanned_activity",
                "match_method": None,
                "match_confidence": None,
                "data_quality": [],
            }
        )
    for activity in unidentified:
        entries.append(
            {
                "planned": None,
                "actual": _actual_summary(activity),
                "state": "unplanned_activity",
                "match_method": None,
                "match_confidence": None,
                "data_quality": [{"reason": "missing_activity_id"}],
            }
        )
    return {
        "entries": entries,
        "provenance": {
            "activities_examined": activities_examined,
            "detail_requests": detail_requests,
            "max_activities": max_activities,
            "truncated": truncated,
            "detail": detail,
        },
    }
