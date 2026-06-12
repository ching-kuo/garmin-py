"""Serializers for health-domain Garmin Connect payloads."""
from __future__ import annotations

from typing import Any

from garmin_cli.serializers._common import (
    _coalesce,
    _get_nested,
    _hours,
    _km,
    _listify,
    _minutes,
)

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
COLUMNS_BODY_BATTERY = ("date", "start_level", "end_level")
COLUMNS_STRESS = ("date", "avg_stress", "max_stress")
COLUMNS_SPO2 = ("date", "avg_spo2", "lowest_spo2")
COLUMNS_RESTING_HR = ("date", "resting_hr")
COLUMNS_READINESS = ("date", "score", "level")
COLUMNS_STATUS = ("date", "training_status", "load_type")
COLUMNS_DAILY_SUMMARY = (
    "date",
    "total_steps",
    "distance_km",
    "active_kilocalories",
    "floors_ascended",
    "floors_descended",
    "moderate_intensity_minutes",
    "vigorous_intensity_minutes",
    "resting_heart_rate",
)
COLUMNS_STEPS = ("date", "total_steps", "total_distance", "step_goal")
COLUMNS_INTENSITY_MINUTES = ("date", "moderate_value", "vigorous_value", "weekly_goal")


def serialize_sleep(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else [raw]
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
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
                "last_night": _coalesce(item.get("lastNightAvg"), item.get("lastNight")),
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
            "last_night": _coalesce(summary.get("lastNightAvg"), summary.get("lastNight")),
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


def serialize_body_battery(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _listify(raw):
        values = item.get("bodyBatteryValuesArray")
        if not isinstance(values, list) or not values:
            continue
        start = values[0] if isinstance(values[0], list) else []
        end = values[-1] if isinstance(values[-1], list) else []
        timestamp = start[0] if len(start) > 0 else None
        rows.append(
            {
                "date": str(timestamp).split("T", 1)[0] if timestamp else item.get("calendarDate"),
                "start_level": start[1] if len(start) > 1 else None,
                "end_level": end[1] if len(end) > 1 else None,
            }
        )
    return rows


def serialize_stress(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _listify(raw):
        values = item.get("stressValuesArray")
        if not isinstance(values, list) or not values:
            date_str = item.get("calendarDate")
        else:
            first_value = values[0] if isinstance(values[0], list) else []
            timestamp = first_value[0] if len(first_value) > 0 else None
            date_str = str(timestamp).split("T", 1)[0] if timestamp else item.get("calendarDate")
        rows.append(
            {
                "date": date_str,
                "avg_stress": item.get("avgStressLevel"),
                "max_stress": item.get("maxStressLevel"),
            }
        )
    return rows


def serialize_spo2(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("dateTime"),
            "avg_spo2": item.get("averageSpO2"),
            "lowest_spo2": item.get("lowestSpO2"),
        }
        for item in _listify(raw)
    ]


def serialize_resting_hr(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "resting_hr": item.get("restingHeartRateValue"),
        }
        for item in _listify(raw)
    ]


def serialize_training_readiness(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "score": item.get("score"),
            "level": item.get("level"),
        }
        for item in _listify(raw)
    ]


def serialize_training_status(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "training_status": item.get("trainingStatusType"),
            "load_type": item.get("trainingLoadType"),
        }
        for item in _listify(raw)
    ]


def serialize_daily_summary(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "total_steps": item.get("totalSteps"),
            "distance_km": _km(item.get("totalDistanceMeters")),
            "active_kilocalories": item.get("activeKilocalories"),
            "floors_ascended": item.get("floorsAscended"),
            "floors_descended": item.get("floorsDescended"),
            "moderate_intensity_minutes": item.get("moderateIntensityMinutes"),
            "vigorous_intensity_minutes": item.get("vigorousIntensityMinutes"),
            "resting_heart_rate": item.get("restingHeartRate"),
        }
        for item in _listify(raw)
    ]


def serialize_steps(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "total_steps": item.get("totalSteps"),
            "total_distance": item.get("totalDistance"),
            "step_goal": item.get("stepGoal"),
        }
        for item in _listify(raw)
    ]


def serialize_intensity_minutes(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "moderate_value": item.get("moderateValue"),
            "vigorous_value": item.get("vigorousValue"),
            "weekly_goal": item.get("weeklyGoal"),
        }
        for item in _listify(raw)
    ]
