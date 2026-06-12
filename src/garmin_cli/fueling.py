"""Fueling-workflow API helpers backed by Garmin Connect APIs."""
from __future__ import annotations

import logging
from datetime import datetime

from garmin_cli import backend as garth
from garmin_cli.zones import ms_to_pace

logger = logging.getLogger(__name__)

# ── Endpoint templates ────────────────────────────────────────────────────
_GET_WORKOUT = "/workout-service/workout/{workout_id}"
_CALENDAR_WEEK = "/calendar-service/year/{year}/month/{month}/day/{day}/start/{start}"
_CALENDAR_MONTH = "/calendar-service/year/{year}/month/{month}"
_LACTATE_THRESHOLD = "/biometric-service/biometric/latestLactateThreshold"
_POWER_TO_WEIGHT = "/biometric-service/biometric/powerToWeight/latest/{date}/"


# ── Public helpers ────────────────────────────────────────────────────────

def get_workout(workout_id: str) -> dict:
    """Fetch a single workout by ID."""
    return {"workout": garth.get_workout(workout_id)}


def get_calendar(
    year: int,
    month: int,
    day: int | None = None,
    start: int = 1,
) -> dict:
    """Fetch calendar data (weekly if *day* given, otherwise monthly).

    *month* is 1-based (human-readable); converted to 0-based for Garmin.
    """
    if not (1900 <= year <= 2100):
        raise ValueError(f"Year must be 1900–2100, got {year}")
    if not (1 <= month <= 12):
        raise ValueError(f"Month must be 1–12, got {month}")
    if day is not None and not (1 <= day <= 31):
        raise ValueError(f"Day must be 1–31, got {day}")

    garmin_month = month - 1  # Garmin API uses 0-based months

    if day is not None:
        endpoint = _CALENDAR_WEEK.format(
            year=year, month=garmin_month, day=day, start=start,
        )
        view_type = "week"
    else:
        endpoint = _CALENDAR_MONTH.format(year=year, month=garmin_month)
        view_type = "month"

    return {
        "calendar": garth.connectapi(endpoint),
        "view_type": view_type,
        "period": {
            "year": year,
            "month": month,
            "day": day,
            "start": start if day else None,
        },
    }


# ── Thresholds / biometrics ───────────────────────────────────────────────

def get_lactate_threshold() -> dict | list | None:
    """Fetch the user's latest lactate threshold (HR + pace)."""
    try:
        data = garth.connectapi(_LACTATE_THRESHOLD)
        if data:
            logger.info("Fetched lactate threshold.")
            return data
    except Exception as exc:
        logger.debug("latestLactateThreshold failed: %s", exc)

    return get_power_to_weight(sport="Running")


def get_power_to_weight(sport: str = "Running") -> dict | list | None:
    """Fetch powerToWeight data for a sport (Running / Cycling / Swimming)."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        data = garth.connectapi(
            _POWER_TO_WEIGHT.format(date=today),
            params={"sport": sport},
        )
        if data:
            logger.info("Fetched powerToWeight (sport=%s).", sport)
            return data
    except Exception as exc:
        logger.debug("powerToWeight (sport=%s) failed: %s", sport, exc)
    return None


def get_all_user_thresholds() -> dict:
    """Aggregate performance thresholds across running, cycling, and swimming."""
    metrics: dict = {}

    # ── Running ───────────────────────────────────────────────────────────
    lt_data = get_lactate_threshold()
    if lt_data:
        items = lt_data if isinstance(lt_data, list) else [lt_data]
        for entry in items:
            if not isinstance(entry, dict):
                continue
            speed = entry.get("speed")
            if speed and speed > 0:
                speed_ms = speed * 10  # Garmin scale → actual m/s
                metrics["running_lt_pace_ms"] = speed_ms
                metrics["running_lt_pace"] = ms_to_pace(speed_ms)
            hr = entry.get("hearRate") or entry.get("heartRate")
            if hr:
                metrics["running_lt_hr_bpm"] = int(hr)

    ptw_running = get_power_to_weight(sport="Running")
    if ptw_running:
        items = ptw_running if isinstance(ptw_running, list) else [ptw_running]
        for entry in items:
            if not isinstance(entry, dict):
                continue
            ftp = entry.get("functionalThresholdPower")
            if ftp:
                metrics["running_threshold_power_watts"] = int(ftp)
            weight = entry.get("weight")
            if weight:
                metrics["weight_kg"] = float(weight)

    # ── Cycling ───────────────────────────────────────────────────────────
    ptw_cycling = get_power_to_weight(sport="Cycling")
    if ptw_cycling:
        items = ptw_cycling if isinstance(ptw_cycling, list) else [ptw_cycling]
        for entry in items:
            if not isinstance(entry, dict):
                continue
            ftp = entry.get("functionalThresholdPower")
            if ftp:
                metrics["cycling_ftp_watts"] = int(ftp)

    return metrics


# ── Update workout description ────────────────────────────────────────────

def update_workout_description(
    workout_id: str,
    workout_data: dict,
    fueling_text: str,
    max_length: int = 1024,
) -> None:
    """Append *fueling_text* to the workout description and PUT back to Garmin.

    If the combined text exceeds *max_length* (Garmin's limit is 1024),
    the fueling text is truncated with an ellipsis.
    """
    existing = workout_data.get("description") or ""

    separator = "\n\n---\n" if existing else ""
    combined = f"{existing}{separator}{fueling_text}"

    if len(combined) > max_length:
        # Truncate the fueling portion, keeping the original description intact
        available: int = max_length - len(existing) - len(separator) - 3  # "..."
        if available > 20:
            truncated = fueling_text[:available]
            combined = f"{existing}{separator}{truncated}..."
        else:
            # Not enough room — just keep original
            logger.warning(
                "Workout description too long to append fueling plan; skipping."
            )
            return

    updated = {**workout_data, "description": combined}

    endpoint = _GET_WORKOUT.format(workout_id=workout_id)
    garth.connectapi(
        endpoint,
        method="PUT",
        json=updated,
        capability="workout_description_update",
    )
    logger.info("Updated workout %s description on Garmin.", workout_id)
