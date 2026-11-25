"""Unit conversion and formatting helpers shared across layers.

Neutral, dependency-free utilities for converting and formatting the raw
numeric units returned by Garmin Connect (speeds, paces, lactate-threshold
payloads). Lives below both the endpoint and serializer layers so either can
import from here without creating a cross-layer dependency.
"""
from __future__ import annotations

import math
from typing import Any


def to_minutes(value: Any) -> float | None:
    """Convert a seconds value to minutes (None-safe, no rounding)."""
    return None if value is None else value / 60


def to_hours(value: Any) -> float | None:
    """Convert a seconds value to hours (None-safe, no rounding)."""
    return None if value is None else value / 3600


def to_km(value: Any) -> float | None:
    """Convert a meters value to kilometers (None-safe, no rounding)."""
    return None if value is None else value / 1000


def to_kmh(value: Any) -> float | None:
    """Convert a meters-per-second value to km/h (None-safe, no rounding)."""
    return None if value is None else value * 3.6


def _mmss(seconds: float) -> str | None:
    """Format seconds as M:SS, rounded to the nearest second; None unless finite and >= 0."""
    if not math.isfinite(seconds) or seconds < 0:
        return None
    # Rounding happens on the total, so divmod carries 59.6 s into the next minute.
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}:{secs:02d}"


def pace_from_speed(speed: Any) -> str | None:
    if speed is None or isinstance(speed, bool):
        return None
    try:
        speed_value = float(speed)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(speed_value) or speed_value <= 0:
        return None
    return _mmss(1000 / speed_value)


def format_pace_seconds(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        if ":" in value:
            return value
        try:
            value = float(value)
        except ValueError:
            return value
    if isinstance(value, (int, float)):
        return _mmss(value)
    return None


def _garmin_pace(speed: Any) -> str | None:
    if speed is None or isinstance(speed, bool):
        return None
    try:
        return pace_from_speed(float(speed) * 10)
    except (TypeError, ValueError):
        return None


def parse_flat_lactate(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Parse flat Garmin lactate threshold items (no sport key) into per-sport dicts."""
    by_sport: dict[str, dict[str, Any]] = {}
    for item in items:
        # "hearRate" is Garmin's typo on the wire, not ours.
        hr = item.get("hearRate") or item.get("heartRate")
        if hr is not None:
            by_sport.setdefault("running", {})["lactateThresholdHeartRate"] = hr
        speed = item.get("speed")
        if speed is not None:
            by_sport.setdefault("running", {})["lactateThresholdPace"] = _garmin_pace(speed)
        cycling_hr = item.get("heartRateCycling")
        if cycling_hr is not None:
            by_sport.setdefault("cycling", {})["lactateThresholdHeartRate"] = cycling_hr
        row_speed = item.get("rowSpeed")
        if row_speed is not None:
            by_sport.setdefault("rowing", {})["lactateThresholdPace"] = _garmin_pace(row_speed)
    return by_sport
