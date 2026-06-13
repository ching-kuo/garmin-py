"""Serializers for activity-domain Garmin Connect payloads.

Covers the activity list/summary/detail surface (registry-driven union
projection), lap and HR-zone breakdowns, metric descriptors, the capability
manifest, multisport children, the activity-weather column constant, and
lifecycle mutation (download/upload/delete) result rows.
"""
from __future__ import annotations

from typing import Any

from garmin_cli.metrics.registry import (
    CYCLING_TYPE_KEYS,
    LAP_SWIM_TYPE_KEYS,
    REGISTRY,
    RUNNING_TYPE_KEYS,
    resolve as _resolve_metric,
)
from garmin_cli.metrics.sport_profile import (
    UNION_COLUMNS,
    SportProfile,
    profile_for,
)
from garmin_cli.serializers._common import (
    _coalesce,
    _get_nested,
    _km,
    _minutes,
)
from garmin_cli.units import pace_from_speed

COLUMNS_ACTIVITY_SUMMARY = (
    "id",
    "date",
    "name",
    "type",
    "distance_km",
    "duration_min",
    "avg_hr",
)
COLUMNS_ACTIVITY_DETAIL = UNION_COLUMNS
COLUMNS_MULTISPORT_CHILDREN = (
    "id",
    "sport",
    "name",
    "distance_km",
    "duration_min",
    "avg_hr",
    "avg_pace",
    "calories",
)
COLUMNS_ACTIVITY_WEATHER = (
    "temperature",
    "weatherIconCode",
    "windSpeed",
    "windDirectionDegrees",
    "humidity",
    "precipProbability",
)


def _iter_activity_pairs(raw: Any) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    items = raw if isinstance(raw, list) else [raw]
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in items:
        activity = item if isinstance(item, dict) else {}
        raw_summary = activity.get("summaryDTO")
        summary = raw_summary if isinstance(raw_summary, dict) else {}
        pairs.append((activity, summary))
    return pairs


def _normalize_activity_base(activity: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": activity.get("activityId"),
        "date": _coalesce(activity.get("startTimeLocal"), summary.get("startTimeLocal")),
        "name": activity.get("activityName"),
        "type": _get_nested(activity, "activityType", "typeKey"),
        "distance_km": _km(_coalesce(activity.get("distance"), summary.get("distance"))),
        "duration_min": _minutes(_coalesce(activity.get("duration"), summary.get("duration"))),
        "avg_hr": _coalesce(activity.get("averageHR"), summary.get("averageHR")),
    }


def serialize_activity_summary(raw: Any) -> list[dict[str, Any]]:
    return [_normalize_activity_base(a, s) for a, s in _iter_activity_pairs(raw)]


_PACE_SPORTS: frozenset[str] = frozenset({
    "running", "trail_running", "treadmill_running",
    "open_water_swimming", "lap_swimming", "swimming",
})


def _project_union_row(activity: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    """Project every UNION_COLUMNS key for one activity using the registry."""
    return {
        key: _resolve_metric(REGISTRY[key], activity, summary)
        for key in UNION_COLUMNS
    }


def serialize_activity_detail(raw: Any) -> list[dict[str, Any]]:
    """Return one row per activity with the stable union-schema keys.

    Every key in ``COLUMNS_ACTIVITY_DETAIL`` (the union schema) is present in
    each row. Sport-inapplicable metrics resolve to ``None`` so downstream
    JSON/CSV consumers see a stable shape regardless of activity type.
    Sport-aware table rendering uses :func:`columns_for_sport` to subset.
    """
    return [_project_union_row(a, s) for a, s in _iter_activity_pairs(raw)]


# --- Activity laps ----------------------------------------------------------
# Run/bike laps share a single shape unioning cycling power + running dynamics;
# non-applicable fields render as None. Pool-swim lengths use a swim-specific
# shape; OWS laps fall through to run/bike.

COLUMNS_ACTIVITY_LAPS_RUN_BIKE: tuple[str, ...] = (
    "lap_index",
    "duration_min",
    "distance_km",
    "avg_hr",
    "max_hr",
    "avg_power_w",
    "max_power_w",
    "norm_power_w",
    "avg_ground_contact_time",
    "avg_vertical_oscillation",
    "avg_vertical_ratio",
    "avg_stride_length",
)


COLUMNS_ACTIVITY_LAPS_SWIM: tuple[str, ...] = (
    "lap_index",
    "duration_min",
    "distance_km",
    "swolf",
    "stroke_type",
    "strokes",
    "avg_stroke_rate",
)


COLUMNS_ACTIVITY_LAPS_CYCLING: tuple[str, ...] = (
    "lap_index",
    "duration_min",
    "distance_km",
    "avg_hr",
    "max_hr",
    "avg_power_w",
    "max_power_w",
    "norm_power_w",
)


COLUMNS_ACTIVITY_LAPS_RUNNING: tuple[str, ...] = (
    "lap_index",
    "duration_min",
    "distance_km",
    "avg_hr",
    "max_hr",
    "avg_ground_contact_time",
    "avg_vertical_oscillation",
    "avg_vertical_ratio",
    "avg_stride_length",
)


def _is_swim_profile(profile: SportProfile) -> bool:
    return bool(profile.type_keys & LAP_SWIM_TYPE_KEYS)


def _lap_row_run_bike(item: dict[str, Any], idx: int) -> dict[str, Any]:
    return {
        "lap_index": idx,
        "duration_min": _minutes(item.get("duration")),
        "distance_km": _km(item.get("distance")),
        "avg_hr": item.get("averageHR"),
        "max_hr": item.get("maxHR"),
        "avg_power_w": item.get("averagePower"),
        "max_power_w": item.get("maxPower"),
        "norm_power_w": _coalesce(item.get("normalizedPower"), item.get("normPower")),
        "avg_ground_contact_time": item.get("avgGroundContactTime"),
        "avg_vertical_oscillation": item.get("avgVerticalOscillation"),
        "avg_vertical_ratio": item.get("avgVerticalRatio"),
        "avg_stride_length": item.get("avgStrideLength"),
    }


def _lap_row_swim(item: dict[str, Any], idx: int) -> dict[str, Any]:
    duration = _coalesce(
        item.get("duration"),
        item.get("lengthSeconds"),
        item.get("activeDuration"),
    )
    distance = _coalesce(item.get("distance"), item.get("lengthDistance"))
    stroke_type = _coalesce(
        item.get("swimStroke"),
        item.get("strokeType"),
        _get_nested(item, "stroke", "swimStrokeKey"),
    )
    strokes = _coalesce(
        item.get("strokes"),
        item.get("numberOfStrokes"),
        item.get("totalNumberOfStrokes"),
    )
    stroke_rate = _coalesce(
        item.get("averageSwimCadenceInStrokesPerMinute"),
        item.get("avgStrokeRate"),
        item.get("averageStrokeRate"),
    )
    return {
        "lap_index": idx,
        "duration_min": _minutes(duration),
        "distance_km": _km(distance),
        "swolf": item.get("swolf"),
        "stroke_type": stroke_type,
        "strokes": strokes,
        "avg_stroke_rate": stroke_rate,
    }


def serialize_activity_laps(
    activity: dict[str, Any],
    splits_payload: dict[str, Any] | None,
    profile: SportProfile | None = None,
) -> list[dict[str, Any]]:
    """Serialize lap-level rows from a splits or typed-splits payload.

    Routes by sport profile: pool-swim activities project ``lengthDTOs`` into
    per-pool-length rows; everything else (run, bike, OWS, default) projects
    ``lapDTOs`` into per-lap rows. Returns an empty list when the payload is
    missing or empty.
    """
    if profile is None:
        type_key = _get_nested(activity, "activityType", "typeKey") if isinstance(activity, dict) else None
        profile = profile_for(type_key)

    payload = splits_payload if isinstance(splits_payload, dict) else {}

    if _is_swim_profile(profile):
        items = payload.get("lengthDTOs") or []
        return [
            _lap_row_swim(item, idx)
            for idx, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]

    items = payload.get("lapDTOs") or []
    return [
        _lap_row_run_bike(item, idx)
        for idx, item in enumerate(items, start=1)
        if isinstance(item, dict)
    ]


def columns_for_lap(profile: SportProfile) -> tuple[str, ...]:
    """Return the column order to render lap rows for the given sport profile."""
    if _is_swim_profile(profile):
        return COLUMNS_ACTIVITY_LAPS_SWIM
    # Sport-aware cycling vs running narrowing — non-applicable columns omit
    # for cleaner table rendering. JSON/CSV consumers should use the run/bike
    # union shape for stable parsing.
    type_keys = profile.type_keys
    if type_keys & CYCLING_TYPE_KEYS:
        return COLUMNS_ACTIVITY_LAPS_CYCLING
    if type_keys & RUNNING_TYPE_KEYS:
        return COLUMNS_ACTIVITY_LAPS_RUNNING
    return COLUMNS_ACTIVITY_LAPS_RUN_BIKE


# --- Activity HR zones ------------------------------------------------------

COLUMNS_ACTIVITY_HR_ZONES: tuple[str, ...] = (
    "zone",
    "zone_low_bpm",
    "zone_high_bpm",
    "minutes_in_zone",
)


def serialize_activity_hr_zones(zones: Any) -> list[dict[str, Any]]:
    """Serialize per-zone time-in-zone rows from get_activity_hr_in_timezones."""
    if not isinstance(zones, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in zones:
        if not isinstance(item, dict):
            continue
        seconds = _coalesce(
            item.get("secsInZone"),
            item.get("secondsInZone"),
            item.get("timeInZone"),
        )
        rows.append(
            {
                "zone": _coalesce(item.get("zoneNumber"), item.get("zone")),
                "zone_low_bpm": _coalesce(
                    item.get("zoneLowBoundary"),
                    item.get("zoneLow"),
                ),
                "zone_high_bpm": _coalesce(
                    item.get("zoneHighBoundary"),
                    item.get("zoneHigh"),
                ),
                "seconds_in_zone": seconds,
                "minutes_in_zone": _minutes(seconds),
            }
        )
    rows.sort(key=lambda row: (row.get("zone") if row.get("zone") is not None else 999))  # type: ignore[arg-type,return-value]
    return rows


# --- Activity metric descriptors --------------------------------------------

COLUMNS_METRICS_DESCRIPTORS: tuple[str, ...] = ("key", "unit", "metricsIndex")


def serialize_metrics_descriptors(details: Any) -> list[dict[str, Any]]:
    """Project metricDescriptors entries from get_activity_details payload."""
    if not isinstance(details, dict):
        return []
    raw_descriptors = details.get("metricDescriptors")
    if not isinstance(raw_descriptors, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw_descriptors:
        if not isinstance(item, dict):
            continue
        unit_value: Any = item.get("unit")
        if isinstance(unit_value, dict):
            unit_value = _coalesce(unit_value.get("key"), unit_value.get("name"))
        rows.append(
            {
                "key": item.get("key"),
                "unit": unit_value,
                "metricsIndex": _coalesce(item.get("metricsIndex"), item.get("index")),
            }
        )
    return rows


# --- Capability manifest ----------------------------------------------------

MANIFEST_REASON_NOT_APPLICABLE = "not_applicable_to_sport"
MANIFEST_REASON_ABSENT = "absent_in_response"


def serialize_capability_manifest(
    activity: dict[str, Any],
    projected_values: dict[str, Any] | None = None,
    *,
    leg_index: int | None = None,
) -> list[dict[str, Any]]:
    """Build a list of unavailable-metric entries for ``activity``.

    Iterates the full metric registry. For each entry, emits at most one of:
    ``not_applicable_to_sport`` when the activity's typeKey is not in the
    entry's ``sports`` set, or ``absent_in_response`` when the entry was
    projected with a None value. Universal entries (``sports=None``) only ever
    surface as ``absent_in_response``. ``leg_index`` is set on every entry to
    attribute it to a specific multisport child leg when provided.
    """
    type_key = None
    if isinstance(activity, dict):
        activity_type = activity.get("activityType")
        if isinstance(activity_type, dict):
            type_key = activity_type.get("typeKey")

    entries: list[dict[str, Any]] = []
    for entry in REGISTRY.values():
        if entry.sports is not None and (type_key is None or type_key not in entry.sports):
            entries.append({
                "field": entry.key,
                "reason": MANIFEST_REASON_NOT_APPLICABLE,
                "leg_index": leg_index,
            })
            continue
        if projected_values is not None and entry.key in projected_values and projected_values[entry.key] is None:
            entries.append({
                "field": entry.key,
                "reason": MANIFEST_REASON_ABSENT,
                "leg_index": leg_index,
            })
    return entries


def manifest_summary_counts(manifest: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (not_applicable_count, absent_count) for a manifest list."""
    not_applicable = sum(1 for e in manifest if e.get("reason") == MANIFEST_REASON_NOT_APPLICABLE)
    absent = sum(1 for e in manifest if e.get("reason") == MANIFEST_REASON_ABSENT)
    return not_applicable, absent


# --- Activity lifecycle (download / upload / delete) ------------------------

COLUMNS_ACTIVITY_DOWNLOAD: tuple[str, ...] = ("id", "format", "path", "size_bytes")
COLUMNS_ACTIVITY_UPLOAD: tuple[str, ...] = ("file", "status", "activity_id")
COLUMNS_ACTIVITY_DELETE: tuple[str, ...] = ("id", "status")


def serialize_activity_download(
    activity_id: Any,
    fmt: str,
    path: str,
    size_bytes: int,
) -> list[dict[str, Any]]:
    """Build one-row serialization for a successful activity download."""
    return [{"id": activity_id, "format": fmt, "path": path, "size_bytes": size_bytes}]


def serialize_activity_upload(
    file_path: str,
    raw_response: Any,
) -> list[dict[str, Any]]:
    """Build one-row serialization for an activity upload result.

    Extracts the new activity ID from the upstream response when available.
    The upstream shape is variable: a dict with ``detailedImportResult`` or
    ``{status, fileName}`` or a bare dict with ``activityId``. Garmin returns
    HTTP 200 even when an import is rejected (e.g. duplicate activity), so a
    ``detailedImportResult`` carrying ``failures`` with no ``successes`` is
    reported as ``rejected`` rather than ``uploaded``.
    """
    activity_id: Any = None
    status = "uploaded"

    if isinstance(raw_response, dict):
        # Shape 1: {detailedImportResult: {successes: [...], failures: [...]}}
        detailed = raw_response.get("detailedImportResult")
        if isinstance(detailed, dict):
            successes = detailed.get("successes") or []
            failures = detailed.get("failures") or []
            if successes and isinstance(successes[0], dict):
                activity_id = successes[0].get("internalId")
            elif failures:
                status = "rejected"
        # Shape 2: bare activityId key
        if activity_id is None and status != "rejected":
            activity_id = raw_response.get("activityId") or raw_response.get("activity_id")
        # Honour explicit status from upstream
        upstream_status = raw_response.get("status")
        if upstream_status:
            status = str(upstream_status)

    return [{"file": file_path, "status": status, "activity_id": activity_id}]


def serialize_activity_delete(activity_id: Any) -> list[dict[str, Any]]:
    """Build one-row serialization for a successful activity delete."""
    return [{"id": activity_id, "status": "deleted"}]


def serialize_multisport_children(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        activity_type = child.get("activityType")
        type_key = activity_type.get("typeKey") if isinstance(activity_type, dict) else None
        raw_summary = child.get("summaryDTO")
        summary = raw_summary if isinstance(raw_summary, dict) else {}
        distance = _coalesce(child.get("distance"), summary.get("distance"))
        duration = _coalesce(child.get("duration"), summary.get("duration"))
        avg_hr = _coalesce(child.get("averageHR"), summary.get("averageHR"))
        avg_speed = _coalesce(child.get("averageSpeed"), summary.get("averageSpeed"))
        calories = _coalesce(child.get("calories"), summary.get("calories"))
        show_pace = avg_speed and type_key in _PACE_SPORTS
        rows.append(
            {
                "id": child.get("activityId"),
                "sport": type_key,
                "name": child.get("activityName"),
                "distance_km": _km(distance),
                "duration_min": _minutes(duration),
                "avg_hr": avg_hr,
                "avg_pace": pace_from_speed(avg_speed) if show_pace else None,
                "calories": calories,
            }
        )
    return rows
