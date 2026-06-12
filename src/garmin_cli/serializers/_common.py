"""Shared private helpers used across serializer domains.

Cross-domain value-walking, coalescing and listify helpers plus the cell-format
unit converters. The converters delegate to :mod:`garmin_cli.units` so the
serializer and metric-registry layers share one canonical implementation.
"""
from __future__ import annotations

from typing import Any

from garmin_cli.units import to_hours, to_km, to_kmh, to_minutes


def _minutes(value: Any) -> float | None:
    return to_minutes(value)


def _hours(value: Any) -> float | None:
    return to_hours(value)


def _km(value: Any) -> float | None:
    return to_km(value)


def _kmh(value: Any) -> float | None:
    return to_kmh(value)


def _get_nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _listify(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def select_latest_dated_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated_rows = [
        row for row in rows if isinstance(row.get("date"), str) and row.get("date")
    ]
    if not dated_rows:
        return rows[:1]
    latest_date = max(row["date"] for row in dated_rows)
    return [row for row in rows if row.get("date") == latest_date]
