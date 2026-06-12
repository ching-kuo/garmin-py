"""Serializers for performance-domain Garmin Connect payloads.

Covers lactate thresholds, VO2 max, lactate-threshold zones, race predictions,
and endurance/hill scores, plus their COLUMNS_* constants.
"""
from __future__ import annotations

from typing import Any

from garmin_cli.serializers._common import _coalesce, _listify
from garmin_cli.units import format_pace_seconds, pace_from_speed, parse_flat_lactate

COLUMNS_RACE_PREDICTIONS = ("race_type", "predicted_time_seconds", "distance_meters")
COLUMNS_ENDURANCE_SCORE = ("date", "overall_score", "endurance_classification")
COLUMNS_HILL_SCORE = ("date", "overall_score", "endurance_score", "strength_score")
COLUMNS_THRESHOLDS = ("sport", "lt_hr_bpm", "lt_pace", "ftp_watts", "weight_kg")
COLUMNS_VO2MAX = ("date", "vo2max", "sport")
COLUMNS_ZONES = ("sport", "lt_hr_bpm", "lt_pace")


_VO2MAX_NON_SPORT_KEYS: frozenset[str] = frozenset({"userId", "heatAltitudeAcclimation"})


def serialize_race_predictions(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        items = _listify(
            raw.get("racePredictions") or raw.get("predictions") or raw
        )
    else:
        items = _listify(raw)
    return [
        {
            "race_type": _coalesce(
                item.get("raceType"),
                item.get("predictionType"),
                item.get("eventType"),
                item.get("displayName"),
            ),
            "predicted_time_seconds": _coalesce(
                item.get("predictedTimeInSeconds"),
                item.get("predictedTime"),
                item.get("timeInSeconds"),
                item.get("time"),
            ),
            "distance_meters": _coalesce(
                item.get("distanceMeters"),
                item.get("raceDistance"),
                item.get("distance"),
            ),
        }
        for item in items
    ]


def serialize_endurance_score(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "overall_score": item.get("overallScore"),
            "endurance_classification": item.get("enduranceClassification"),
        }
        for item in _listify(raw)
    ]


def serialize_hill_score(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "overall_score": item.get("overallScore"),
            "endurance_score": item.get("enduranceScore"),
            "strength_score": item.get("strengthScore"),
        }
        for item in _listify(raw)
    ]


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
    items = _listify(raw.get("value") if isinstance(raw, dict) and isinstance(raw.get("value"), dict) else raw)
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
    rows: list[dict[str, Any]] = []
    for item in items:
        threshold = item if isinstance(item, dict) else {}
        rows.append(
            {
                "sport": threshold.get("sport"),
                "lt_hr_bpm": threshold.get("lactateThresholdHeartRate"),
                "lt_pace": format_pace_seconds(threshold.get("lactateThresholdPace")),
                "ftp_watts": threshold.get("functionalThresholdPower"),
                "weight_kg": threshold.get("weight"),
            }
        )
    return rows
