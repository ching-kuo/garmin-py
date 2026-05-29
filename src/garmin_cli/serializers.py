"""Serializer helpers for Garmin Connect payloads."""
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
    columns_for_sport,
    profile_for,
)


COLUMNS_SLEEP = (
    "date",
    "duration_hours",
    "deep_min",
    "light_min",
    "rem_min",
    "awake_min",
    "score",
)
COLUMNS_HRV = ("date", "weekly_avg", "last_night", "status")
COLUMNS_WEIGHT = ("date", "weight_kg", "bmi", "body_fat_pct")
COLUMNS_BODY_BATTERY = ("date", "start_level", "end_level")
COLUMNS_STRESS = ("date", "avg_stress", "max_stress")
COLUMNS_SPO2 = ("date", "avg_spo2", "lowest_spo2")
COLUMNS_RESTING_HR = ("date", "resting_hr")
COLUMNS_READINESS = ("date", "score", "level")
COLUMNS_STATUS = ("date", "training_status", "load_type")
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
COLUMNS_CALENDAR_WORKOUT = ("date", "id", "name", "type", "duration_min", "description")
COLUMNS_WORKOUT = ("id", "name", "sport", "duration_min", "description")
COLUMNS_WORKOUT_DETAIL = (
    "id",
    "name",
    "sport",
    "duration_min",
    "description",
    "steps_summary",
)
COLUMNS_THRESHOLDS = ("sport", "lt_hr_bpm", "lt_pace", "ftp_watts", "weight_kg")
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
COLUMNS_VO2MAX = ("date", "vo2max", "sport")
COLUMNS_ZONES = ("sport", "lt_hr_bpm", "lt_pace")
COLUMNS_WORKOUT_MUTATE = ("id", "name", "sport", "duration_min", "status")


def _minutes(value: Any) -> float | None:
    return None if value is None else value / 60


def _hours(value: Any) -> float | None:
    return None if value is None else value / 3600


def _km(value: Any) -> float | None:
    return None if value is None else value / 1000


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


def _pace_from_speed(speed: Any) -> str | None:
    if speed is None:
        return None
    try:
        speed_value = float(speed)
    except (TypeError, ValueError):
        return None
    if speed_value <= 0:
        return None
    total_seconds = int(1000 / speed_value)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _format_pace_seconds(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        if ":" in value:
            return value
        try:
            value = float(value)
        except ValueError:
            return value
    if isinstance(value, (int, float)):
        total_seconds = int(value)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"
    return None


def select_latest_dated_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated_rows = [
        row for row in rows if isinstance(row.get("date"), str) and row.get("date")
    ]
    if not dated_rows:
        return rows[:1]
    latest_date = max(row["date"] for row in dated_rows)
    return [row for row in rows if row.get("date") == latest_date]


_VO2MAX_NON_SPORT_KEYS: frozenset[str] = frozenset({"userId", "heatAltitudeAcclimation"})


def _garmin_pace(speed: Any) -> str | None:
    if speed is None:
        return None
    try:
        return _pace_from_speed(float(speed) * 10)
    except (TypeError, ValueError):
        return None


def _parse_flat_lactate(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
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


def _normalize_workout_base(workout: dict[str, Any]) -> dict[str, Any]:
    duration_seconds = _coalesce(
        workout.get("estimatedDurationInSecs"),
        workout.get("estimatedDuration"),
        workout.get("duration"),
    )
    raw_sport_type = workout.get("sportType")
    sport_type = raw_sport_type if isinstance(raw_sport_type, dict) else {}
    return {
        "id": _coalesce(workout.get("workoutId"), workout.get("id")),
        "name": _coalesce(workout.get("workoutName"), workout.get("name")),
        "sport": _coalesce(
            sport_type.get("sportTypeKey"),
            sport_type.get("displayName"),
            sport_type.get("key"),
            workout.get("sport"),
            workout.get("type"),
        ),
        "duration_min": _minutes(duration_seconds),
        "description": workout.get("description"),
    }


def serialize_sleep(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else [raw]
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dto = item.get("dailySleepDTO") or item
        rows.append(
            {
                "date": dto.get("calendarDate"),
                "duration_hours": _hours(dto.get("sleepTimeSeconds")),
                "deep_min": _minutes(dto.get("deepSleepSeconds")),
                "light_min": _minutes(dto.get("lightSleepSeconds")),
                "rem_min": _minutes(dto.get("remSleepSeconds")),
                "awake_min": _minutes(dto.get("awakeSleepSeconds")),
                "score": _get_nested(dto, "sleepScores", "overall", "value"),
            }
        )
    return rows


def serialize_hrv(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []

    range_items = raw.get("hrvSummaries")
    if isinstance(range_items, list):
        return [
            {
                "date": item.get("calendarDate"),
                "weekly_avg": item.get("weeklyAvg"),
                "last_night": _coalesce(item.get("lastNightAvg"), item.get("lastNight")),
                "status": item.get("status"),
            }
            for item in range_items
            if isinstance(item, dict)
        ]

    summary = raw.get("hrvSummary")
    if not isinstance(summary, dict) or not summary:
        return []

    return [
        {
            "date": summary.get("calendarDate"),
            "weekly_avg": summary.get("weeklyAvg"),
            "last_night": _coalesce(summary.get("lastNightAvg"), summary.get("lastNight")),
            "status": summary.get("status"),
        }
    ]


def serialize_weight(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("dateWeightList", []) if isinstance(raw, dict) else []
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "date": item.get("calendarDate"),
                "weight_kg": None if item.get("weight") is None else item.get("weight") / 1000,
                "bmi": item.get("bmi"),
                "body_fat_pct": item.get("bodyFat"),
            }
        )
    return rows


def serialize_body_battery(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _listify(raw):
        values = item.get("bodyBatteryValuesArray")
        if not isinstance(values, list) or not values:
            continue
        start = values[0] if isinstance(values[0], list) else []
        end = values[-1] if isinstance(values[-1], list) else []
        timestamp = start[0] if len(start) > 0 else None
        rows.append(
            {
                "date": str(timestamp).split("T", 1)[0] if timestamp else item.get("calendarDate"),
                "start_level": start[1] if len(start) > 1 else None,
                "end_level": end[1] if len(end) > 1 else None,
            }
        )
    return rows


def serialize_stress(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _listify(raw):
        values = item.get("stressValuesArray")
        if not isinstance(values, list) or not values:
            date_str = item.get("calendarDate")
        else:
            first_value = values[0] if isinstance(values[0], list) else []
            timestamp = first_value[0] if len(first_value) > 0 else None
            date_str = str(timestamp).split("T", 1)[0] if timestamp else item.get("calendarDate")
        rows.append(
            {
                "date": date_str,
                "avg_stress": item.get("avgStressLevel"),
                "max_stress": item.get("maxStressLevel"),
            }
        )
    return rows


def serialize_spo2(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("dateTime"),
            "avg_spo2": item.get("averageSpO2"),
            "lowest_spo2": item.get("lowestSpO2"),
        }
        for item in _listify(raw)
    ]


def serialize_resting_hr(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "resting_hr": item.get("restingHeartRateValue"),
        }
        for item in _listify(raw)
    ]


def serialize_training_readiness(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "score": item.get("score"),
            "level": item.get("level"),
        }
        for item in _listify(raw)
    ]


def serialize_training_status(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "training_status": item.get("trainingStatusType"),
            "load_type": item.get("trainingLoadType"),
        }
        for item in _listify(raw)
    ]


def serialize_daily_summary(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "total_steps": item.get("totalSteps"),
            "distance_km": _km(item.get("totalDistanceMeters")),
            "active_kilocalories": item.get("activeKilocalories"),
            "floors_ascended": item.get("floorsAscended"),
            "floors_descended": item.get("floorsDescended"),
            "moderate_intensity_minutes": item.get("moderateIntensityMinutes"),
            "vigorous_intensity_minutes": item.get("vigorousIntensityMinutes"),
            "resting_heart_rate": item.get("restingHeartRate"),
        }
        for item in _listify(raw)
    ]


def serialize_steps(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "total_steps": item.get("totalSteps"),
            "total_distance": item.get("totalDistance"),
            "step_goal": item.get("stepGoal"),
        }
        for item in _listify(raw)
    ]


def serialize_intensity_minutes(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": item.get("calendarDate"),
            "moderate_value": item.get("moderateValue"),
            "vigorous_value": item.get("vigorousValue"),
            "weekly_goal": item.get("weeklyGoal"),
        }
        for item in _listify(raw)
    ]


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


def serialize_device(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "device_id": item.get("deviceId"),
            "display_name": item.get("displayName"),
            "device_type": item.get("deviceTypeName"),
            "last_sync_time": item.get("lastSyncTime"),
        }
        for item in _listify(raw)
    ]


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
    rows.sort(key=lambda row: (row.get("zone") if row.get("zone") is not None else 999))
    return rows


# --- Activity metric descriptors --------------------------------------------


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
                "avg_pace": _pace_from_speed(avg_speed) if show_pace else None,
                "calories": calories,
            }
        )
    return rows


def serialize_calendar_workout(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("calendarItems", []) if isinstance(raw, dict) else []
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "date": item.get("date"),
                "id": _coalesce(item.get("workoutId"), item.get("id")),
                "name": item.get("title"),
                "type": item.get("workoutTypeKey"),
                "duration_min": _minutes(item.get("durationInSeconds")),
                "description": item.get("note"),
            }
        )
    return rows


def serialize_workout_summary(raw: Any) -> list[dict[str, Any]]:
    return [_normalize_workout_base(item) for item in _listify(raw)]


def serialize_workout_detail(raw: Any) -> list[dict[str, Any]]:
    workout = raw if isinstance(raw, dict) else {}
    row = _normalize_workout_base(workout)
    steps: list[dict[str, Any]] = []
    for segment in workout.get("workoutSegments", []):
        if not isinstance(segment, dict):
            continue
        for step in segment.get("workoutSteps", []):
            if not isinstance(step, dict):
                continue
            steps.append(
                {
                    "step_order": _coalesce(step.get("stepOrder"), step.get("order")),
                    "step_type": _coalesce(
                        _get_nested(step, "stepType", "stepTypeKey"),
                        step.get("stepTypeKey"),
                        step.get("type"),
                    ),
                    "duration_type": step.get("durationType"),
                    "duration_value": step.get("durationValue"),
                    "target_type": _coalesce(
                        step.get("targetType"),
                        _get_nested(step, "target", "targetType"),
                    ),
                    "target_value_low": _coalesce(step.get("targetValueOne"), step.get("targetValueLow")),
                    "target_value_high": _coalesce(step.get("targetValueTwo"), step.get("targetValueHigh")),
                }
            )
    row["steps"] = steps
    row["steps_summary"] = " > ".join(
        step_type for step in steps if (step_type := step.get("step_type"))
    )
    return [row]


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
        by_sport = _parse_flat_lactate(items)
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
            _format_pace_seconds(item.get("lactateThresholdPace")),
            _pace_from_speed(item.get("lactateThresholdSpeed")),
        )
        rows.append(
            {
                "sport": item.get("sport"),
                "lt_hr_bpm": item.get("lactateThresholdHeartRate"),
                "lt_pace": pace,
            }
        )
    return rows


def serialize_workout_mutate(raw: Any, status: str) -> list[dict[str, Any]]:
    """Serialize a create/update response with a status field."""
    row = _normalize_workout_base(raw if isinstance(raw, dict) else {})
    return [{**row, "status": status}]


def serialize_thresholds(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("thresholds", []) if isinstance(raw, dict) else []
    rows: list[dict[str, Any]] = []
    for item in items:
        threshold = item if isinstance(item, dict) else {}
        rows.append(
            {
                "sport": threshold.get("sport"),
                "lt_hr_bpm": threshold.get("lactateThresholdHeartRate"),
                "lt_pace": _format_pace_seconds(threshold.get("lactateThresholdPace")),
                "ftp_watts": threshold.get("functionalThresholdPower"),
                "weight_kg": threshold.get("weight"),
            }
        )
    return rows
