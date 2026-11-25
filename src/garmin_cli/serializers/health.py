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

from garmin_cli.metrics import FieldEntry, FieldTable
from garmin_cli.serializers._common import (
    _get_nested,
    _hours,
    _km,
    _listify,
    _local_iso,
    _minutes,
)

COLUMNS_BODY_BATTERY = ("date", "start_level", "end_level", "max_level")
COLUMNS_STRESS = ("date", "avg_stress", "max_stress")


# --- Declarative field tables ------------------------------------------------
# Each COLUMNS_* constant is derived from its table's entry order.

_SLEEP_TABLE = FieldTable(
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
COLUMNS_SLEEP = _SLEEP_TABLE.columns

_HRV_TABLE = FieldTable(
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("weekly_avg", (("weeklyAvg",),)),
        # lastNightAvg is the modern key; lastNight is the legacy fallback.
        FieldEntry("last_night", (("lastNightAvg",), ("lastNight",))),
        FieldEntry("status", (("status",),)),
    ),
)
COLUMNS_HRV = _HRV_TABLE.columns

_WEIGHT_TABLE = FieldTable(
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("weight_kg", (("weight",),), lambda grams: grams / 1000),
        FieldEntry("bmi", (("bmi",),)),
        FieldEntry("body_fat_pct", (("bodyFat",),)),
    ),
)
COLUMNS_WEIGHT = _WEIGHT_TABLE.columns

_SPO2_TABLE = FieldTable(
    entries=(
        FieldEntry("date", (("dateTime",),)),
        FieldEntry("avg_spo2", (("averageSpO2",),)),
        FieldEntry("lowest_spo2", (("lowestSpO2",),)),
    ),
)
COLUMNS_SPO2 = _SPO2_TABLE.columns

_RESTING_HR_TABLE = FieldTable(
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        # restingHeartRate is the displayName-scoped dailyHeartRate response
        # (current); restingHeartRateValue is the legacy bare-path key kept
        # as a fallback.
        FieldEntry("resting_hr", (("restingHeartRate",), ("restingHeartRateValue",))),
    ),
)
COLUMNS_RESTING_HR = _RESTING_HR_TABLE.columns

_READINESS_TABLE = FieldTable(
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("score", (("score",),)),
        FieldEntry("level", (("level",),)),
    ),
)
COLUMNS_READINESS = _READINESS_TABLE.columns

# Projects the per-device dict merged by serialize_training_status: load-
# balance entry keys, status entry keys, and the flattened acuteTrainingLoadDTO
# all live side by side in one flat dict. Monthly load buckets and their
# Target ranges are Garmin's 4-week load-focus numbers; the load tunnel is the
# chronic-load band Garmin considers productive.
_STATUS_TABLE = FieldTable(
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("training_status", (("trainingStatusFeedbackPhrase",),)),
        FieldEntry("acute_load", (("dailyTrainingLoadAcute",),)),
        FieldEntry("chronic_load", (("dailyTrainingLoadChronic",),)),
        FieldEntry("acwr", (("dailyAcuteChronicWorkloadRatio",),)),
        FieldEntry("acwr_status", (("acwrStatus",),)),
        FieldEntry("load_tunnel_min", (("minTrainingLoadChronic",),)),
        FieldEntry("load_tunnel_max", (("maxTrainingLoadChronic",),)),
        FieldEntry("monthly_load_aerobic_low", (("monthlyLoadAerobicLow",),)),
        FieldEntry("monthly_load_aerobic_high", (("monthlyLoadAerobicHigh",),)),
        FieldEntry("monthly_load_anaerobic", (("monthlyLoadAnaerobic",),)),
        FieldEntry("aerobic_low_target_min", (("monthlyLoadAerobicLowTargetMin",),)),
        FieldEntry("aerobic_low_target_max", (("monthlyLoadAerobicLowTargetMax",),)),
        FieldEntry("aerobic_high_target_min", (("monthlyLoadAerobicHighTargetMin",),)),
        FieldEntry("aerobic_high_target_max", (("monthlyLoadAerobicHighTargetMax",),)),
        FieldEntry("anaerobic_target_min", (("monthlyLoadAnaerobicTargetMin",),)),
        FieldEntry("anaerobic_target_max", (("monthlyLoadAnaerobicTargetMax",),)),
        FieldEntry("load_balance_status", (("trainingBalanceFeedbackPhrase",),)),
    ),
)
COLUMNS_STATUS = _STATUS_TABLE.columns

_DAILY_SUMMARY_TABLE = FieldTable(
    entries=(
        # Nested v2 ``dailysummaries`` shape (verified live 2026-11-09).
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("total_steps", (("movement", "steps", "value"),)),
        FieldEntry("distance_km", (("movement", "steps", "distanceInMeters"),), _km),
        FieldEntry("active_kilocalories", (("calories", "burnedActive"),)),
        FieldEntry("floors_ascended", (("movement", "floorsAscended", "value"),)),
        FieldEntry("floors_descended", (("movement", "floorsDescended", "value"),)),
        FieldEntry("moderate_intensity_minutes", (("intensityMinutes", "moderate"),)),
        FieldEntry("vigorous_intensity_minutes", (("intensityMinutes", "vigorous"),)),
        FieldEntry("resting_heart_rate", (("heartRate", "restingValue"),)),
    ),
)
COLUMNS_DAILY_SUMMARY = _DAILY_SUMMARY_TABLE.columns

_STEPS_TABLE = FieldTable(
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("total_steps", (("totalSteps",),)),
        FieldEntry("total_distance", (("totalDistance",),)),
        FieldEntry("step_goal", (("stepGoal",),)),
    ),
)
COLUMNS_STEPS = _STEPS_TABLE.columns

_INTENSITY_MINUTES_TABLE = FieldTable(
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("moderate_value", (("moderateValue",),)),
        FieldEntry("vigorous_value", (("vigorousValue",),)),
        FieldEntry("weekly_goal", (("weeklyGoal",),)),
    ),
)
COLUMNS_INTENSITY_MINUTES = _INTENSITY_MINUTES_TABLE.columns


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
        date_str = item.get("date") or item.get("calendarDate") or _sample_iso_date(values)
        rows.append(
            {
                "date": date_str,
                "start_level": levels[0] if levels else None,
                "end_level": levels[-1] if levels else None,
                "max_level": max(levels) if levels else None,
            }
        )
    return rows


def _sample_iso_date(values: Any) -> str | None:
    """Date of the first ``[timestamp, value]`` sample when it is an ISO string.

    Legacy per-day shapes carried ISO timestamps. Live samples are GMT epoch
    millis, whose UTC date can be the day before the account-local date, so
    those yield None instead of a wrong date.
    """
    first = values[0] if isinstance(values, list) and values and isinstance(values[0], list) else []
    timestamp = first[0] if first else None
    return timestamp.split("T", 1)[0] if isinstance(timestamp, str) and "T" in timestamp else None


def serialize_stress(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _listify(raw):
        rows.append(
            {
                "date": item.get("calendarDate") or _sample_iso_date(item.get("stressValuesArray")),
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


def _primary_device_item(device_map: Any) -> tuple[str | None, dict[str, Any]]:
    """Pick the primary-device (key, entry) pair from a deviceId-keyed dict.

    The aggregated training-status payload nests its status and load-balance
    data one level down in dicts keyed by deviceId string. Prefer the entry
    flagged ``primaryTrainingDevice``; fall back to the first entry. The map
    key is returned alongside because live entries may omit an inner
    ``deviceId`` field.
    """
    if not isinstance(device_map, dict):
        return None, {}
    items = [
        (key, value) for key, value in device_map.items() if isinstance(value, dict)
    ]
    for key, entry in items:
        if entry.get("primaryTrainingDevice"):
            return key, entry
    return items[0] if items else (None, {})


def serialize_training_status(raw: Any) -> list[dict[str, Any]]:
    """Serialize the aggregated training-status payload into one flat row.

    Merges the primary device's status entry (with its nested
    ``acuteTrainingLoadDTO`` flattened in) and load-balance entry, then
    projects the merged dict through the declarative table.
    """
    rows: list[dict[str, Any]] = []
    for item in _listify(raw):
        status_key, status = _primary_device_item(
            _get_nested(item, "mostRecentTrainingStatus", "latestTrainingStatusData")
        )
        balance_map = _get_nested(
            item, "mostRecentTrainingLoadBalance", "metricsTrainingLoadBalanceDTOMap"
        )
        # Keep both halves on the same device: match the balance entry by the
        # status entry's deviceId (inner field, else its map key). Never merge
        # a different device's balance data; missing match -> empty balance.
        device_id = status.get("deviceId") or status_key
        keyed = balance_map.get(str(device_id)) if isinstance(balance_map, dict) else None
        if isinstance(keyed, dict):
            balance = keyed
        elif device_id is None:
            _, balance = _primary_device_item(balance_map)
        else:
            balance = {}
        acute = status.get("acuteTrainingLoadDTO")
        merged = {
            **balance,
            **status,
            **(acute if isinstance(acute, dict) else {}),
        }
        rows.append(_STATUS_TABLE.project(merged))
    return rows


def serialize_daily_summary(raw: Any) -> list[dict[str, Any]]:
    return _DAILY_SUMMARY_TABLE.project_all(_listify(raw))


def serialize_steps(raw: Any) -> list[dict[str, Any]]:
    return _STEPS_TABLE.project_all(_listify(raw))


def serialize_intensity_minutes(raw: Any) -> list[dict[str, Any]]:
    return _INTENSITY_MINUTES_TABLE.project_all(_listify(raw))
