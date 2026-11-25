"""Serializers for performance-domain Garmin Connect payloads.

Covers lactate thresholds, VO2 max, HR/power zone tables, race predictions,
and endurance/hill scores, plus their COLUMNS_* constants.

The flat-row serializers (race predictions, endurance score, hill score,
thresholds) are declared as
:class:`~garmin_cli.metrics.field_table.FieldTable` instances -- each column's
wire source(s) and converter live in one entry, and the published COLUMNS_*
order is derived from the table's entries. Two
serializers keep bespoke code because they are structural rather than flat:
:func:`serialize_vo2max` fans one wire item out into one row per sport sub-dict,
and :func:`serialize_zones` turns per-sport zone floors into low/high rows.
"""
from __future__ import annotations

import math
from typing import Any

from garmin_cli.metrics import FieldEntry, FieldTable
from garmin_cli.serializers._common import _coalesce, _listify
from garmin_cli.units import format_pace_seconds

COLUMNS_VO2MAX = ("date", "vo2max", "sport")
COLUMNS_ZONES = ("kind", "sport", "zone", "low", "high", "unit")


_VO2MAX_NON_SPORT_KEYS: frozenset[str] = frozenset({"userId", "heatAltitudeAcclimation"})


# --- Declarative field tables ------------------------------------------------

_RACE_PREDICTIONS_TABLE = FieldTable(
    entries=(
        FieldEntry(
            "race_type",
            (("raceType",), ("predictionType",), ("eventType",), ("displayName",)),
        ),
        FieldEntry(
            "predicted_time_seconds",
            (
                ("predictedTimeInSeconds",),
                ("predictedTime",),
                ("timeInSeconds",),
                ("time",),
            ),
        ),
        FieldEntry(
            "distance_meters",
            (("distanceMeters",), ("raceDistance",), ("distance",)),
        ),
    ),
)
COLUMNS_RACE_PREDICTIONS = _RACE_PREDICTIONS_TABLE.columns

_ENDURANCE_SCORE_TABLE = FieldTable(
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("overall_score", (("overallScore",),)),
        FieldEntry("endurance_classification", (("enduranceClassification",),)),
    ),
)
COLUMNS_ENDURANCE_SCORE = _ENDURANCE_SCORE_TABLE.columns

_HILL_SCORE_TABLE = FieldTable(
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("overall_score", (("overallScore",),)),
        FieldEntry("endurance_score", (("enduranceScore",),)),
        FieldEntry("strength_score", (("strengthScore",),)),
    ),
)
COLUMNS_HILL_SCORE = _HILL_SCORE_TABLE.columns

# Garmin identifies each personal record only by an undocumented integer
# typeId. Labels for 1-8 were verified against live values (times/distances
# match known PRs); 9-10 and 12-15 follow the community-documented mapping
# used by the garmin-connect JS client and fit the observed values (e.g.
# typeId 10 on a "Zwift FTP test" ride). Unmapped ids (11 and swim records
# 16-22) surface with label None and the raw value; units per label suffix
# (_s seconds, _m meters, _w watts).
_PR_TYPE_LABELS: dict[int, str] = {
    1: "fastest_1km_s",
    2: "fastest_1mi_s",
    3: "fastest_5km_s",
    4: "fastest_10km_s",
    5: "fastest_half_marathon_s",
    6: "fastest_marathon_s",
    7: "longest_run_m",
    8: "longest_ride_m",
    9: "total_ascent_m",
    10: "max_avg_power_20min_w",
    12: "most_steps_day",
    13: "most_steps_week",
    14: "most_steps_month",
    15: "longest_goal_streak_days",
}


def _pr_label(type_id: Any) -> str | None:
    return _PR_TYPE_LABELS.get(type_id) if isinstance(type_id, int) else None


def _date_part(value: Any) -> Any:
    return value.split("T", 1)[0] if isinstance(value, str) else value


_PERSONAL_RECORDS_TABLE = FieldTable(
    entries=(
        FieldEntry("type_id", (("typeId",),)),
        FieldEntry("label", (("typeId",),), _pr_label),
        FieldEntry("value", (("value",),)),
        FieldEntry("activity_type", (("activityType",),)),
        FieldEntry(
            "date",
            (
                ("activityStartDateTimeLocalFormatted",),
                ("prStartTimeLocalFormatted",),
                ("prStartTimeGmtFormatted",),
            ),
            _date_part,
        ),
        FieldEntry("activity_id", (("activityId",),)),
        FieldEntry("activity_name", (("activityName",),)),
    ),
)
COLUMNS_PERSONAL_RECORDS = _PERSONAL_RECORDS_TABLE.columns


_THRESHOLDS_TABLE = FieldTable(
    entries=(
        FieldEntry("sport", (("sport",),)),
        FieldEntry("lt_hr_bpm", (("lactateThresholdHeartRate",),)),
        FieldEntry("lt_pace", (("lactateThresholdPace",),), format_pace_seconds),
        FieldEntry("ftp_watts", (("functionalThresholdPower",),)),
        FieldEntry("weight_kg", (("weight",),)),
    ),
)
COLUMNS_THRESHOLDS = _THRESHOLDS_TABLE.columns


# The displayName-scoped race-predictions endpoint returns one flat dict
# with a fixed field per race distance (time5K, time10K, ...) rather than a
# list of per-race objects. Each entry maps that field to the row shape the
# table below already knows how to project (raceType/predictedTimeInSeconds/
# distanceMeters), so the reshape stays entirely upstream of the table.
_RACE_PREDICTION_FLAT_FIELDS: tuple[tuple[str, str, float], ...] = (
    ("time5K", "5K", 5000.0),
    ("time10K", "10K", 10000.0),
    ("timeHalfMarathon", "Half Marathon", 21097.5),
    ("timeMarathon", "Marathon", 42195.0),
)


def serialize_race_predictions(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and any(key in raw for key, _, _ in _RACE_PREDICTION_FLAT_FIELDS):
        items: list[dict[str, Any]] = [
            {
                "raceType": race_type,
                "predictedTimeInSeconds": raw[key],
                "distanceMeters": distance_meters,
            }
            for key, race_type, distance_meters in _RACE_PREDICTION_FLAT_FIELDS
            if raw.get(key) is not None
        ]
    elif isinstance(raw, dict):
        items = _listify(
            raw.get("racePredictions") or raw.get("predictions") or raw
        )
    else:
        items = _listify(raw)
    return _RACE_PREDICTIONS_TABLE.project_all(items)


def serialize_personal_records(raw: Any) -> list[dict[str, Any]]:
    # The live endpoint returns a flat list; anything else (None, a wrapper
    # dict, an error body) must yield zero rows, not one all-null row.
    items = raw if isinstance(raw, list) else []
    return _PERSONAL_RECORDS_TABLE.project_all(
        [item for item in items if isinstance(item, dict)]
    )


def serialize_endurance_score(raw: Any) -> list[dict[str, Any]]:
    return _ENDURANCE_SCORE_TABLE.project_all(_listify(raw))


def serialize_hill_score(raw: Any) -> list[dict[str, Any]]:
    return _HILL_SCORE_TABLE.project_all(_listify(raw))


def serialize_vo2max(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(raw, dict) and "maxMetData" in raw:
        max_met_data = raw.get("maxMetData")
        items = _listify(max_met_data)
    else:
        items = _listify(raw)
    rows: list[dict[str, Any]] = []
    for item in items:
        wrapped_metrics = [
            (sport_name, sport_payload)
            for sport_name, sport_payload in item.items()
            if sport_name not in _VO2MAX_NON_SPORT_KEYS
            and isinstance(sport_payload, dict)
        ]
        if wrapped_metrics:
            for sport_name, sport_payload in wrapped_metrics:
                rows.append(
                    {
                        "date": _coalesce(sport_payload.get("calendarDate"), item.get("calendarDate")),
                        "vo2max": _coalesce(sport_payload.get("vo2MaxValue"), sport_payload.get("vo2max")),
                        "sport": sport_name.lower(),
                    }
                )
            continue
        rows.append(
            {
                "date": _coalesce(item.get("calendarDate"), item.get("date")),
                "vo2max": _coalesce(item.get("vo2MaxValue"), item.get("vo2max")),
                "sport": item.get("sport"),
            }
        )
    return [row for row in rows if row.get("date") is not None or row.get("vo2max") is not None]


def _is_finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _zone_rows(item: dict[str, Any], kind: str, unit: str, zone_count: int, top: Any = None) -> list[dict[str, Any]]:
    """Zone rows from zone<N>Floor values; *top* is the top zone's known ceiling."""
    floors: list[float] = []
    ended = False
    for number in range(1, zone_count + 1):
        floor = item.get(f"zone{number}Floor")
        # Unused zones read 0.0 or null after the last one (live RUNNING power
        # zones 6-7); only such a trailing run marks the end of the table.
        if floor is None or (floor == 0 and floors):
            ended = True
            continue
        if ended or not _is_finite(floor) or floor < 0 or (floors and floor <= floors[-1]):
            # A gap before a later floor, or a floor that does not rise, is
            # not a usable table.
            return []
        floors.append(floor)
    if len(floors) < 2:
        # An unconfigured (all-zero) table bounds no zone.
        return []
    # The top zone is open-ended unless a finite ceiling above its floor is known.
    top_high = top if _is_finite(top) and top > floors[-1] else None
    sport = item.get("sport")
    return [
        {
            "kind": kind,
            "sport": sport.lower() if isinstance(sport, str) else sport,
            "zone": number,
            "low": low,
            # A zone ends below the next floor.
            "high": floors[number] if number < len(floors) else top_high,
            "unit": unit,
        }
        for number, low in enumerate(floors, start=1)
    ]


def serialize_zones(raw: Any) -> list[dict[str, Any]]:
    """Flatten get_zone_tables() output to one row per (kind, sport, zone)."""
    tables = raw if isinstance(raw, dict) else {}
    return [
        *(
            row
            for item in _listify(tables.get("heart_rate"))
            for row in _zone_rows(item, "heart_rate", "bpm", 5, item.get("maxHeartRateUsed"))
        ),
        *(row for item in _listify(tables.get("power")) for row in _zone_rows(item, "power", "W", 7)),
    ]


def serialize_thresholds(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("thresholds", []) if isinstance(raw, dict) else []
    # Legacy emitted an all-None row for non-dict items (``{}.get(...)``); map
    # non-dicts to ``{}`` so row count and shape stay byte-identical.
    return [
        _THRESHOLDS_TABLE.project(item if isinstance(item, dict) else {})
        for item in items
    ]
