"""Serializers for performance trend payloads.

Covers FTP history, heat/altitude acclimation, cycling ability, power curve,
and fastest splits. Every table mirrors a wire shape observed live on
2026-11-09; units follow the column suffix (_s seconds, _w watts, _m meters).
"""
from __future__ import annotations

from typing import Any

from garmin_cli.metrics import FieldEntry, FieldTable, validate_table_coverage
from garmin_cli.serializers._common import _listify

COLUMNS_FTP_HISTORY = ("date", "sport", "ftp_watts")
COLUMNS_ACCLIMATION = (
    "date",
    "heat_acclimation_pct",
    "heat_trend",
    "altitude_acclimation",
    "altitude_trend",
    "current_altitude",
)
COLUMNS_CYCLING_ABILITY = (
    "date",
    "aerobic_endurance",
    "aerobic_capacity",
    "anaerobic_capacity",
    "profile_type",
    "aerobic_endurance_feedback",
    "aerobic_capacity_feedback",
    "anaerobic_capacity_feedback",
)
COLUMNS_POWER_CURVE = ("duration_s", "power_w", "activity_id", "activity_date")
COLUMNS_FASTEST_SPLITS = ("distance_m", "time_s", "activity_id", "activity_date")


def _one_decimal(value: Any) -> Any:
    return round(value, 1) if isinstance(value, (int, float)) else value


_FTP_HISTORY_TABLE = FieldTable(
    name="ftp_history",
    columns=COLUMNS_FTP_HISTORY,
    entries=(
        FieldEntry("date", (("from",),)),
        FieldEntry("sport", (("series",),)),
        FieldEntry("ftp_watts", (("value",),)),
    ),
)

_ACCLIMATION_TABLE = FieldTable(
    name="acclimation",
    columns=COLUMNS_ACCLIMATION,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("heat_acclimation_pct", (("heatAcclimationPercentage",),)),
        FieldEntry("heat_trend", (("heatTrend",),)),
        FieldEntry("altitude_acclimation", (("altitudeAcclimation",),)),
        FieldEntry("altitude_trend", (("altitudeTrend",),)),
        FieldEntry("current_altitude", (("currentAltitude",),)),
    ),
)

_CYCLING_ABILITY_TABLE = FieldTable(
    name="cycling_ability",
    columns=COLUMNS_CYCLING_ABILITY,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("aerobic_endurance", (("aerobicEndurance",),)),
        FieldEntry("aerobic_capacity", (("aerobicCapacity",),)),
        FieldEntry("anaerobic_capacity", (("anaerobicCapacity",),)),
        FieldEntry("profile_type", (("profileType",),)),
        FieldEntry("aerobic_endurance_feedback", (("aerobicEnduranceFeedback",),)),
        FieldEntry("aerobic_capacity_feedback", (("aerobicCapacityFeedback",),)),
        FieldEntry("anaerobic_capacity_feedback", (("anaerobicCapacityFeedback",),)),
    ),
)

_POWER_CURVE_TABLE = FieldTable(
    name="power_curve",
    columns=COLUMNS_POWER_CURVE,
    entries=(
        FieldEntry("duration_s", (("duration",),)),
        FieldEntry("power_w", (("power",),)),
        FieldEntry("activity_id", (("activityId",),)),
        FieldEntry("activity_date", (("activityDate",),)),
    ),
)

_FASTEST_SPLITS_TABLE = FieldTable(
    name="fastest_splits",
    columns=COLUMNS_FASTEST_SPLITS,
    entries=(
        FieldEntry("distance_m", (("distance",),)),
        FieldEntry("time_s", (("time",),), _one_decimal),
        FieldEntry("activity_id", (("activityId",),)),
        FieldEntry("activity_date", (("activityDate",),)),
    ),
)


def serialize_ftp_history(raw: Any) -> list[dict[str, Any]]:
    return _FTP_HISTORY_TABLE.project_all(_listify(raw))


def serialize_acclimation(raw: Any) -> list[dict[str, Any]]:
    return _ACCLIMATION_TABLE.project_all(_listify(raw))


def serialize_cycling_ability(raw: Any) -> list[dict[str, Any]]:
    """Flatten the date-keyed ``cyclingAbilitiesMap`` into date-ordered rows."""
    by_date = raw.get("cyclingAbilitiesMap") if isinstance(raw, dict) else None
    if not isinstance(by_date, dict):
        return []
    # The map key is the authoritative date; an item's own calendarDate wins.
    items = [{"calendarDate": key, **by_date[key]} for key in sorted(by_date) if isinstance(by_date[key], dict)]
    return _CYCLING_ABILITY_TABLE.project_all(items)


def serialize_power_curve(raw: Any) -> list[dict[str, Any]]:
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return _POWER_CURVE_TABLE.project_all(_listify(entries))


def serialize_fastest_splits(raw: Any) -> list[dict[str, Any]]:
    return _FASTEST_SPLITS_TABLE.project_all(_listify(raw))


validate_table_coverage(
    "trends",
    {
        "COLUMNS_FTP_HISTORY": COLUMNS_FTP_HISTORY,
        "COLUMNS_ACCLIMATION": COLUMNS_ACCLIMATION,
        "COLUMNS_CYCLING_ABILITY": COLUMNS_CYCLING_ABILITY,
        "COLUMNS_POWER_CURVE": COLUMNS_POWER_CURVE,
        "COLUMNS_FASTEST_SPLITS": COLUMNS_FASTEST_SPLITS,
    },
    (
        _FTP_HISTORY_TABLE,
        _ACCLIMATION_TABLE,
        _CYCLING_ABILITY_TABLE,
        _POWER_CURVE_TABLE,
        _FASTEST_SPLITS_TABLE,
    ),
)
