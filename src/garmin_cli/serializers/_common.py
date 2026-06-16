"""Shared private helpers used across serializer domains.

Cross-domain value-walking, coalescing and listify helpers plus the cell-format
unit converters. The converters delegate to :mod:`garmin_cli.units` so the
serializer and metric-registry layers share one canonical implementation.
"""
from __future__ import annotations

from datetime import datetime, timedelta
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


def _type_key(activity: Any) -> Any:
    """Resolve a sport ``typeKey`` from an activity payload, or None.

    Garmin's activity-service detail payload nulls the top-level
    ``activityType`` on some activities and carries the real sport under
    ``activityTypeDTO``. Both shapes are checked (in that order) so sport
    detection never silently yields None when the type is actually present.
    """
    if not isinstance(activity, dict):
        return None
    return _coalesce(
        _get_nested(activity, "activityType", "typeKey"),
        _get_nested(activity, "activityTypeDTO", "typeKey"),
    )


# Garmin emits naive local/GMT timestamps as e.g. "2026-06-12T23:53:55.0".
_TS_FORMATS: tuple[str, ...] = ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S")


def _parse_garmin_ts(value: Any) -> datetime | None:
    """Parse a Garmin naive timestamp string into a datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1]
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _gmt_local_offset(gmt_value: Any, local_value: Any) -> timedelta | None:
    """Return the local-minus-GMT offset implied by an activity's two stamps."""
    gmt = _parse_garmin_ts(gmt_value)
    local = _parse_garmin_ts(local_value)
    if gmt is None or local is None:
        return None
    return local - gmt


def _local_from_gmt(gmt_value: Any, offset: timedelta | None) -> str | None:
    """Apply a GMT->local *offset* to a GMT timestamp string (ISO-8601 out)."""
    if offset is None:
        return None
    gmt = _parse_garmin_ts(gmt_value)
    if gmt is None:
        return None
    # Garmin stamps are second-resolution; drop any sub-second component so the
    # derived local time never widens to microsecond formatting via isoformat().
    return (gmt + offset).replace(microsecond=0).isoformat()


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
