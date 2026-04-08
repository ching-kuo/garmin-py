"""Serializer helpers for Garmin Connect payloads."""
from __future__ import annotations

from typing import Any


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
COLUMNS_DAILY_SUMMARY = (
    "date",
    "total_steps",
    "distance_km",
    "active_kilocalories",
    "floors_ascended",
    "floors_descended",
    "moderate_intensity_minutes",
    "vigorous_intensity_minutes",
    "resting_heart_rate",
)
COLUMNS_STEPS = ("date", "total_steps", "total_distance", "step_goal")
COLUMNS_INTENSITY_MINUTES = ("date", "moderate_value", "vigorous_value", "weekly_goal")
COLUMNS_RACE_PREDICTIONS = ("race_type", "predicted_time_seconds", "distance_meters")
COLUMNS_ENDURANCE_SCORE = ("date", "overall_score", "endurance_classification")
COLUMNS_HILL_SCORE = ("date", "overall_score", "endurance_score", "strength_score")
COLUMNS_DEVICE = ("device_id", "display_name", "device_type", "last_sync_time")
COLUMNS_ACTIVITY_SUMMARY = (
    "id",
    "date",
    "name",
    "type",
    "distance_km",
    "duration_min",
    "avg_hr",
)
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


def _pace_from_garmin_speed(speed: Any) -> str | None:
    if speed is None:
        return None
    try:
        return _pace_from_speed(float(speed) * 10)
    except (TypeError, ValueError):
        return None


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


_VO2MAX_NON_SPORT_KEYS: frozenset[str] = frozenset({"userId", "heatAltitudeAcclimation"})

# Garmin API field name -- "hearRate" is their typo, not ours
_GARMIN_HR_FIELD = "hearRate"
_GARMIN_HR_FIELD_ALT = "heartRate"


def _parse_flat_lactate(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Parse flat Garmin lactate threshold items (no sport key) into per-sport dicts."""
    by_sport: dict[str, dict[str, Any]] = {}
    for item in items:
        hr = item.get(_GARMIN_HR_FIELD) or item.get(_GARMIN_HR_FIELD_ALT)
        if hr is not None:
            by_sport.setdefault("running", {})["lactateThresholdHeartRate"] = hr
        speed = item.get("speed")
        if speed is not None:
            by_sport.setdefault("running", {})["lactateThresholdPace"] = _pace_from_garmin_speed(speed)
        cycling_hr = item.get("heartRateCycling")
        if cycling_hr is not None:
            by_sport.setdefault("cycling", {})["lactateThresholdHeartRate"] = cycling_hr
        row_speed = item.get("rowSpeed")
        if row_speed is not None:
            by_sport.setdefault("rowing", {})["lactateThresholdPace"] = _pace_from_garmin_speed(row_speed)
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


def serialize_activity_summary(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else [raw]
    rows: list[dict[str, Any]] = []
    for item in items:
        activity = item if isinstance(item, dict) else {}
        rows.append(
            {
                "id": activity.get("activityId"),
                "date": activity.get("startTimeLocal"),
                "name": activity.get("activityName"),
                "type": _get_nested(activity, "activityType", "typeKey"),
                "distance_km": _km(activity.get("distance")),
                "duration_min": _minutes(activity.get("duration")),
                "avg_hr": activity.get("averageHR"),
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
