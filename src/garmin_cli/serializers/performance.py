"""Serializers for performance-domain Garmin Connect payloads.

Covers lactate thresholds, VO2 max, lactate-threshold zones, race predictions,
and endurance/hill scores, plus their COLUMNS_* constants.

The flat-row serializers (race predictions, endurance score, hill score,
thresholds) are declared as
:class:`~garmin_cli.metrics.field_table.FieldTable` instances -- each column's
wire source(s) and converter live in one entry, and the table constructor keeps
the entries in lockstep with the published COLUMNS_* order at import time. Two
serializers keep bespoke code because they are structural rather than flat:
:func:`serialize_vo2max` fans one wire item out into one row per sport sub-dict,
and :func:`serialize_zones` merges multiple flat lactate samples across items
(via :func:`parse_flat_lactate`) and coalesces two pace representations.
"""
from __future__ import annotations

from typing import Any

from garmin_cli.metrics import FieldEntry, FieldTable, validate_table_coverage
from garmin_cli.serializers._common import _coalesce, _listify
from garmin_cli.units import format_pace_seconds, pace_from_speed, parse_flat_lactate

COLUMNS_RACE_PREDICTIONS = ("race_type", "predicted_time_seconds", "distance_meters")
COLUMNS_ENDURANCE_SCORE = ("date", "overall_score", "endurance_classification")
COLUMNS_HILL_SCORE = ("date", "overall_score", "endurance_score", "strength_score")
COLUMNS_THRESHOLDS = ("sport", "lt_hr_bpm", "lt_pace", "ftp_watts", "weight_kg")
COLUMNS_VO2MAX = ("date", "vo2max", "sport")
COLUMNS_ZONES = ("sport", "lt_hr_bpm", "lt_pace")


_VO2MAX_NON_SPORT_KEYS: frozenset[str] = frozenset({"userId", "heatAltitudeAcclimation"})


# --- Declarative field tables ------------------------------------------------

_RACE_PREDICTIONS_TABLE = FieldTable(
    name="race_predictions",
    columns=COLUMNS_RACE_PREDICTIONS,
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

_ENDURANCE_SCORE_TABLE = FieldTable(
    name="endurance_score",
    columns=COLUMNS_ENDURANCE_SCORE,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("overall_score", (("overallScore",),)),
        FieldEntry("endurance_classification", (("enduranceClassification",),)),
    ),
)

_HILL_SCORE_TABLE = FieldTable(
    name="hill_score",
    columns=COLUMNS_HILL_SCORE,
    entries=(
        FieldEntry("date", (("calendarDate",),)),
        FieldEntry("overall_score", (("overallScore",),)),
        FieldEntry("endurance_score", (("enduranceScore",),)),
        FieldEntry("strength_score", (("strengthScore",),)),
    ),
)

_THRESHOLDS_TABLE = FieldTable(
    name="thresholds",
    columns=COLUMNS_THRESHOLDS,
    entries=(
        FieldEntry("sport", (("sport",),)),
        FieldEntry("lt_hr_bpm", (("lactateThresholdHeartRate",),)),
        FieldEntry("lt_pace", (("lactateThresholdPace",),), format_pace_seconds),
        FieldEntry("ftp_watts", (("functionalThresholdPower",),)),
        FieldEntry("weight_kg", (("weight",),)),
    ),
)


def serialize_race_predictions(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        items = _listify(
            raw.get("racePredictions") or raw.get("predictions") or raw
        )
    else:
        items = _listify(raw)
    return _RACE_PREDICTIONS_TABLE.project_all(items)


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


def serialize_zones(raw: Any) -> list[dict[str, Any]]:
    value = raw.get("value") if isinstance(raw, dict) else None
    items = _listify(value if isinstance(value, dict) else raw)
    if items and all(item.get("sport") is None for item in items):
        by_sport = parse_flat_lactate(items)
        return [
            {
                "sport": sport,
                "lt_hr_bpm": payload.get("lactateThresholdHeartRate"),
                "lt_pace": payload.get("lactateThresholdPace"),
            }
            for sport, payload in by_sport.items()
        ]
    rows: list[dict[str, Any]] = []
    for item in items:
        pace = _coalesce(
            format_pace_seconds(item.get("lactateThresholdPace")),
            pace_from_speed(item.get("lactateThresholdSpeed")),
        )
        rows.append(
            {
                "sport": item.get("sport"),
                "lt_hr_bpm": item.get("lactateThresholdHeartRate"),
                "lt_pace": pace,
            }
        )
    return rows


def serialize_thresholds(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("thresholds", []) if isinstance(raw, dict) else []
    # Legacy emitted an all-None row for non-dict items (``{}.get(...)``); map
    # non-dicts to ``{}`` so row count and shape stay byte-identical.
    return [
        _THRESHOLDS_TABLE.project(item if isinstance(item, dict) else {})
        for item in items
    ]


# Import-time guard: COLUMNS_* must stay in lockstep with the declarative
# tables. VO2 max (per-sport fan-out) and zones (cross-item lactate merge) are
# structural and intentionally have no backing table.
validate_table_coverage(
    "performance",
    {
        "COLUMNS_RACE_PREDICTIONS": COLUMNS_RACE_PREDICTIONS,
        "COLUMNS_ENDURANCE_SCORE": COLUMNS_ENDURANCE_SCORE,
        "COLUMNS_HILL_SCORE": COLUMNS_HILL_SCORE,
        "COLUMNS_THRESHOLDS": COLUMNS_THRESHOLDS,
        "COLUMNS_VO2MAX": COLUMNS_VO2MAX,
        "COLUMNS_ZONES": COLUMNS_ZONES,
    },
    (
        _RACE_PREDICTIONS_TABLE,
        _ENDURANCE_SCORE_TABLE,
        _HILL_SCORE_TABLE,
        _THRESHOLDS_TABLE,
    ),
    exempt=frozenset({"COLUMNS_VO2MAX", "COLUMNS_ZONES"}),
)
