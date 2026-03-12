"""Serializer helpers for Garmin Connect payloads."""
from __future__ import annotations

from typing import Any


COLUMNS_SLEEP = (
    "date",
    "duration_hours",
    "deep_min",
    "light_min",
    "rem_min",
    "awake_min",
    "score",
)
COLUMNS_HRV = ("date", "weekly_avg", "last_night", "status")
COLUMNS_WEIGHT = ("date", "weight_kg", "bmi", "body_fat_pct")
COLUMNS_ACTIVITY_SUMMARY = (
    "id",
    "date",
    "name",
    "type",
    "distance_km",
    "duration_min",
    "avg_hr",
)
COLUMNS_CALENDAR_WORKOUT = ("date", "name", "type", "duration_min", "description")
COLUMNS_WORKOUT = ("id", "name", "sport", "duration_min", "description")
COLUMNS_THRESHOLDS = ("sport", "lt_hr_bpm", "lt_pace", "ftp_watts", "weight_kg")
COLUMNS_ACTIVITY_WEATHER = (
    "temperature",
    "weatherIconCode",
    "windSpeed",
    "windDirectionDegrees",
    "humidity",
    "precipProbability",
)
COLUMNS_VO2MAX = ("calendarDate", "vo2MaxValue", "sport")
COLUMNS_LACTATE = ("lactateThresholdHeartRate", "lactateThresholdSpeed", "sport")


def _minutes(value: Any) -> float | None:
    return None if value is None else value / 60


def _hours(value: Any) -> float | None:
    return None if value is None else value / 3600


def _km(value: Any) -> float | None:
    return None if value is None else value / 1000


def _get_nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def serialize_sleep(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else [raw]
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # Real API returns flat items; test mocks may use dailySleepDTO wrapper
        dto = item.get("dailySleepDTO") or item
        rows.append(
            {
                "date": dto.get("calendarDate"),
                "duration_hours": _hours(dto.get("sleepTimeSeconds")),
                "deep_min": _minutes(dto.get("deepSleepSeconds")),
                "light_min": _minutes(dto.get("lightSleepSeconds")),
                "rem_min": _minutes(dto.get("remSleepSeconds")),
                "awake_min": _minutes(dto.get("awakeSleepSeconds")),
                "score": _get_nested(dto, "sleepScores", "overall", "value"),
            }
        )
    return rows


def serialize_hrv(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []

    range_items = raw.get("hrvSummaries")
    if isinstance(range_items, list):
        return [
            {
                "date": item.get("calendarDate"),
                "weekly_avg": item.get("weeklyAvg"),
                "last_night": item.get("lastNight"),
                "status": item.get("status"),
            }
            for item in range_items
            if isinstance(item, dict)
        ]

    summary = raw.get("hrvSummary")
    if not isinstance(summary, dict) or not summary:
        return []

    return [
        {
            "date": summary.get("calendarDate"),
            "weekly_avg": summary.get("weeklyAvg"),
            "last_night": summary.get("lastNight"),
            "status": summary.get("status"),
        }
    ]


def serialize_weight(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("dateWeightList", []) if isinstance(raw, dict) else []
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "date": item.get("calendarDate"),
                "weight_kg": None if item.get("weight") is None else item.get("weight") / 1000,
                "bmi": item.get("bmi"),
                "body_fat_pct": item.get("bodyFat"),
            }
        )
    return rows


def serialize_activity_summary(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else [raw]
    rows: list[dict[str, Any]] = []
    for item in items:
        activity = item if isinstance(item, dict) else {}
        rows.append(
            {
                "id": activity.get("activityId"),
                "date": activity.get("startTimeLocal"),
                "name": activity.get("activityName"),
                "type": _get_nested(activity, "activityType", "typeKey"),
                "distance_km": _km(activity.get("distance")),
                "duration_min": _minutes(activity.get("duration")),
                "avg_hr": activity.get("averageHR"),
            }
        )
    return rows


def serialize_calendar_workout(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("calendarItems", []) if isinstance(raw, dict) else []
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "date": item.get("date"),
                "name": item.get("title"),
                "type": item.get("workoutTypeKey"),
                "duration_min": _minutes(item.get("durationInSeconds")),
                "description": item.get("note"),
            }
        )
    return rows


def serialize_workout_summary(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else [raw]
    rows: list[dict[str, Any]] = []
    for item in items:
        workout = item if isinstance(item, dict) else {}
        rows.append(
            {
                "id": workout.get("workoutId"),
                "name": workout.get("workoutName"),
                "sport": _get_nested(workout, "sportType", "sportTypeKey"),
                "duration_min": _minutes(workout.get("estimatedDurationInSecs")),
                "description": workout.get("description"),
            }
        )
    return rows


def serialize_thresholds(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("thresholds", []) if isinstance(raw, dict) else []
    rows: list[dict[str, Any]] = []
    for item in items:
        threshold = item if isinstance(item, dict) else {}
        rows.append(
            {
                "sport": threshold.get("sport"),
                "lt_hr_bpm": threshold.get("lactateThresholdHeartRate"),
                "lt_pace": threshold.get("lactateThresholdPace"),
                "ftp_watts": threshold.get("functionalThresholdPower"),
                "weight_kg": threshold.get("weight"),
            }
        )
    return rows
