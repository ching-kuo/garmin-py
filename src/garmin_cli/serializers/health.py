"""Serializers for health-domain Garmin Connect payloads.

Most health rows are *flat* projections of one wire dict: ``date`` plus a
handful of value columns, each resolved from one (or a precedence-ordered set
of) wire key(s) with an optional unit converter. Those are declared once as a
:class:`~garmin_cli.metrics.field_table.FieldTable` and projected generically,
the health-domain analogue of the activity metric registry. The two serializers
with genuinely structural input shaping -- :func:`serialize_body_battery` and
:func:`serialize_stress`, which derive ``date`` by indexing into a positional
samples array rather than walking dict keys -- keep bespoke code on top of the
shared converters. ``serialize_sleep`` and ``serialize_hrv`` reshape their input
(DTO unwrap / range-vs-single routing) but still project each row through a
table so the output key order is declaration-driven.
"""
from __future__ import annotations

from typing import Any

from garmin_cli.metrics import FieldEntry, FieldTable, validate_table_coverage
from garmin_cli.serializers._common import (
    _hours,
    _km,
    _listify,
    _local_iso,
    _minutes,
)

COLUMNS_SLEEP = (
    "date",
    "bedtime",
    "wake_time",
    "duration_hours",
    "deep_min",
    "light_min",
    "rem_min",
    "awake_min",
    "score",
)
COLUMNS_HRV = ("date", "weekly_avg", "last_night", "status")
COLUMNS_WEIGHT = ("date", "weight_kg", "bmi", "body_fat_pct")
COLUMNS_BODY_BATTERY = ("date", "start_level", "end_level", "max_level")
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


# --- Declarative field tables ------------------------------------------------
# Each table pairs a COLUMNS_* constant with its per-column resolver. The
# FieldTable constructor asserts the two stay in lockstep at import time.

_SLEEP_TABLE = FieldTable(
    name="sleep",
    columns=COLUMNS_SLEEP,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("bedtime", (("sleepStartTimestampLocal",),), _local_iso),
        FieldEntry("wake_time", (("sleepEndTimestampLocal",),), _local_iso),
        FieldEntry("duration_hours", (("sleepTimeSeconds",),), _hours),
        FieldEntry("deep_min", (("deepSleepSeconds",),), _minutes),
        FieldEntry("light_min", (("lightSleepSeconds",),), _minutes),
        FieldEntry("rem_min", (("remSleepSeconds",),), _minutes),
        FieldEntry("awake_min", (("awakeSleepSeconds",),), _minutes),
        FieldEntry("score", (("sleepScores", "overall", "value"),)),
    ),
)

_HRV_TABLE = FieldTable(
    name="hrv",
    columns=COLUMNS_HRV,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("weekly_avg", (("weeklyAvg",),)),
        # lastNightAvg is the modern key; lastNight is the legacy fallback.
        FieldEntry("last_night", (("lastNightAvg",), ("lastNight",))),
        FieldEntry("status", (("status",),)),
    ),
)

_WEIGHT_TABLE = FieldTable(
    name="weight",
    columns=COLUMNS_WEIGHT,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("weight_kg", (("weight",),), lambda grams: grams / 1000),
        FieldEntry("bmi", (("bmi",),)),
        FieldEntry("body_fat_pct", (("bodyFat",),)),
    ),
)

_SPO2_TABLE = FieldTable(
    name="spo2",
    columns=COLUMNS_SPO2,
    entries=(
        FieldEntry("date", (("dateTime",),)),
        FieldEntry("avg_spo2", (("averageSpO2",),)),
        FieldEntry("lowest_spo2", (("lowestSpO2",),)),
    ),
)

_RESTING_HR_TABLE = FieldTable(
    name="resting_hr",
    columns=COLUMNS_RESTING_HR,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        # restingHeartRate is the displayName-scoped dailyHeartRate response
        # (current); restingHeartRateValue is the legacy bare-path key kept
        # as a fallback.
        FieldEntry("resting_hr", (("restingHeartRate",), ("restingHeartRateValue",))),
    ),
)

_READINESS_TABLE = FieldTable(
    name="readiness",
    columns=COLUMNS_READINESS,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("score", (("score",),)),
        FieldEntry("level", (("level",),)),
    ),
)

_STATUS_TABLE = FieldTable(
    name="training_status",
    columns=COLUMNS_STATUS,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("training_status", (("trainingStatusType",),)),
        FieldEntry("load_type", (("trainingLoadType",),)),
    ),
)

_DAILY_SUMMARY_TABLE = FieldTable(
    name="daily_summary",
    columns=COLUMNS_DAILY_SUMMARY,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("total_steps", (("totalSteps",),)),
        FieldEntry("distance_km", (("totalDistanceMeters",),), _km),
        FieldEntry("active_kilocalories", (("activeKilocalories",),)),
        FieldEntry("floors_ascended", (("floorsAscended",),)),
        FieldEntry("floors_descended", (("floorsDescended",),)),
        FieldEntry("moderate_intensity_minutes", (("moderateIntensityMinutes",),)),
        FieldEntry("vigorous_intensity_minutes", (("vigorousIntensityMinutes",),)),
        FieldEntry("resting_heart_rate", (("restingHeartRate",),)),
    ),
)

_STEPS_TABLE = FieldTable(
    name="steps",
    columns=COLUMNS_STEPS,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("total_steps", (("totalSteps",),)),
        FieldEntry("total_distance", (("totalDistance",),)),
        FieldEntry("step_goal", (("stepGoal",),)),
    ),
)

_INTENSITY_MINUTES_TABLE = FieldTable(
    name="intensity_minutes",
    columns=COLUMNS_INTENSITY_MINUTES,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("moderate_value", (("moderateValue",),)),
        FieldEntry("vigorous_value", (("vigorousValue",),)),
        FieldEntry("weekly_goal", (("weeklyGoal",),)),
    ),
)


def serialize_sleep(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else [raw]
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dto = item.get("dailySleepDTO") or item
        rows.append(_SLEEP_TABLE.project(dto))
    return rows


def serialize_hrv(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []

    range_items = raw.get("hrvSummaries")
    if isinstance(range_items, list):
        return _HRV_TABLE.project_all(
            [item for item in range_items if isinstance(item, dict)]
        )

    summary = raw.get("hrvSummary")
    if not isinstance(summary, dict) or not summary:
        return []

    return [_HRV_TABLE.project(summary)]


def serialize_weight(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("dateWeightList", []) if isinstance(raw, dict) else []
    return _WEIGHT_TABLE.project_all(_listify(items))


def serialize_body_battery(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _listify(raw):
        values = item.get("bodyBatteryValuesArray")
        if not isinstance(values, list) or not values:
            continue
        # Entries are [timestamp, level] pairs; reports/daily uses epoch millis
        # timestamps and carries the calendar date in the item's "date" field.
        levels = [
            entry[1]
            for entry in values
            if isinstance(entry, list) and len(entry) > 1 and isinstance(entry[1], (int, float))
        ]
        date_str = item.get("date") or item.get("calendarDate")
        if not date_str:
            # legacy per-day shape carried ISO timestamps; epoch millis (the
            # reports/daily shape) can't yield a date here, so leave it None
            first = values[0] if isinstance(values[0], list) else []
            timestamp = first[0] if first else None
            date_str = timestamp.split("T", 1)[0] if isinstance(timestamp, str) and "T" in timestamp else None
        rows.append(
            {
                "date": date_str,
                "start_level": levels[0] if levels else None,
                "end_level": levels[-1] if levels else None,
                "max_level": max(levels) if levels else None,
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
    return _SPO2_TABLE.project_all(_listify(raw))


def serialize_resting_hr(raw: Any) -> list[dict[str, Any]]:
    return _RESTING_HR_TABLE.project_all(_listify(raw))


def serialize_training_readiness(raw: Any) -> list[dict[str, Any]]:
    return _READINESS_TABLE.project_all(_listify(raw))


def serialize_training_status(raw: Any) -> list[dict[str, Any]]:
    return _STATUS_TABLE.project_all(_listify(raw))


def serialize_daily_summary(raw: Any) -> list[dict[str, Any]]:
    return _DAILY_SUMMARY_TABLE.project_all(_listify(raw))


def serialize_steps(raw: Any) -> list[dict[str, Any]]:
    return _STEPS_TABLE.project_all(_listify(raw))


def serialize_intensity_minutes(raw: Any) -> list[dict[str, Any]]:
    return _INTENSITY_MINUTES_TABLE.project_all(_listify(raw))


# Import-time guard: every published COLUMNS_* constant must be backed by a
# declarative FieldTable, except the two structural serializers (body battery /
# stress) whose ``date`` is read out of a positional samples array.
validate_table_coverage(
    "health",
    {
        "COLUMNS_SLEEP": COLUMNS_SLEEP,
        "COLUMNS_HRV": COLUMNS_HRV,
        "COLUMNS_WEIGHT": COLUMNS_WEIGHT,
        "COLUMNS_BODY_BATTERY": COLUMNS_BODY_BATTERY,
        "COLUMNS_STRESS": COLUMNS_STRESS,
        "COLUMNS_SPO2": COLUMNS_SPO2,
        "COLUMNS_RESTING_HR": COLUMNS_RESTING_HR,
        "COLUMNS_READINESS": COLUMNS_READINESS,
        "COLUMNS_STATUS": COLUMNS_STATUS,
        "COLUMNS_DAILY_SUMMARY": COLUMNS_DAILY_SUMMARY,
        "COLUMNS_STEPS": COLUMNS_STEPS,
        "COLUMNS_INTENSITY_MINUTES": COLUMNS_INTENSITY_MINUTES,
    },
    (
        _SLEEP_TABLE,
        _HRV_TABLE,
        _WEIGHT_TABLE,
        _SPO2_TABLE,
        _RESTING_HR_TABLE,
        _READINESS_TABLE,
        _STATUS_TABLE,
        _DAILY_SUMMARY_TABLE,
        _STEPS_TABLE,
        _INTENSITY_MINUTES_TABLE,
    ),
    exempt=frozenset({"COLUMNS_BODY_BATTERY", "COLUMNS_STRESS"}),
)
