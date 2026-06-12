"""Performance endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from garmin_cli import backend as garth
from garmin_cli.endpoints._base import _make_request
from garmin_cli.exceptions import GarminCliError
from garmin_cli.units import (
    format_pace_seconds,
    pace_from_speed,
    parse_flat_lactate,
)


def _request(url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _make_request(garth.connectapi, url, params=params)


def get_lactate_threshold() -> Any:
    result = _request("/biometric-service/biometric/latestLactateThreshold")
    return result if result is not None else []


def get_ftp(sport: str) -> Any:
    result = _request(
        f"/biometric-service/biometric/powerToWeight/latest/{date.today().isoformat()}/",
        params={"sport": sport.title()},
    )
    return result if result is not None else []


def get_vo2max(measurement_date: date) -> Any:
    result = _request(
        f"/metrics-service/metrics/maxmet/daily/{measurement_date.isoformat()}/{measurement_date.isoformat()}"
    )
    return result if result is not None else []


def get_latest_vo2max(days_back: int = 30) -> Any:
    end = date.today()
    start = end - timedelta(days=days_back)
    result = _request(
        f"/metrics-service/metrics/maxmet/daily/{start.isoformat()}/{end.isoformat()}"
    )
    return result if result is not None else []


def _optional_ftp(sport: str) -> Any:
    try:
        return get_ftp(sport)
    except GarminCliError as exc:
        if exc.error_code == "NOT_FOUND":
            return []
        raise



def _merge_threshold(
    thresholds_by_sport: dict[str, dict[str, Any]],
    sport: str,
    payload: dict[str, Any],
) -> None:
    row = thresholds_by_sport.setdefault(
        sport,
        {
            "sport": sport,
            "lactateThresholdHeartRate": None,
            "lactateThresholdPace": None,
            "functionalThresholdPower": None,
            "weight": None,
        },
    )
    normalized_payload = dict(payload)
    pace_value = normalized_payload.get("lactateThresholdPace")
    if isinstance(pace_value, (int, float)):
        normalized_payload["lactateThresholdPace"] = format_pace_seconds(pace_value)
    elif normalized_payload.get("lactateThresholdPace") is None:
        normalized_payload["lactateThresholdPace"] = pace_from_speed(
            normalized_payload.get("lactateThresholdSpeed")
        )
    for field in (
        "lactateThresholdHeartRate",
        "lactateThresholdPace",
        "functionalThresholdPower",
        "weight",
    ):
        value = normalized_payload.get(field)
        if value is not None:
            row[field] = value


def _iter_dict_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("value"), dict):
            return [payload["value"]]
        return [payload] if payload else []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict) and item]
    return []


def _normalize_sport(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value:
        return value.lower()
    return fallback


def get_all_thresholds() -> dict[str, Any]:
    lactate = get_lactate_threshold()
    cycling_ftp = _optional_ftp("cycling")
    running_ftp = _optional_ftp("running")

    thresholds_by_sport: dict[str, dict[str, Any]] = {}

    lactate_items = _iter_dict_items(lactate)
    if lactate_items and all(item.get("sport") is None for item in lactate_items):
        for sport, payload in parse_flat_lactate(lactate_items).items():
            _merge_threshold(thresholds_by_sport, sport, payload)
    else:
        for item in lactate_items:
            sport = _normalize_sport(item.get("sport"), "running")
            _merge_threshold(thresholds_by_sport, sport, item)

    for fallback_sport, ftp in (("cycling", cycling_ftp), ("running", running_ftp)):
        for item in _iter_dict_items(ftp):
            sport = _normalize_sport(item.get("sport"), fallback_sport)
            _merge_threshold(thresholds_by_sport, sport, item)

    return {"thresholds": list(thresholds_by_sport.values())}
