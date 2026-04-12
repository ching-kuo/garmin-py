"""Garmin Connect API calls preserved for future use.

These functions are *not* called by the fueling workflow but are kept
so they can be re-integrated later (e.g. for listing activities,
uploading workouts, or scheduling).
"""

from __future__ import annotations

import logging
from datetime import datetime

from garmin_cli import backend as garth
logger = logging.getLogger(__name__)

# ── Endpoint templates ────────────────────────────────────────────────────
_LIST_WORKOUTS = "/workout-service/workouts"
_GET_ACTIVITY = "/activity-service/activity/{activity_id}"
_GET_ACTIVITY_WEATHER = "/activity-service/activity/{activity_id}/weather"
_LIST_ACTIVITIES = "/activitylist-service/activities/search/activities"


def list_workouts() -> dict:
    """List all workouts available on Garmin Connect."""
    return {"workouts": garth.connectapi(_LIST_WORKOUTS)}


def get_activity(activity_id: str) -> dict:
    """Get details of a completed activity by ID."""
    endpoint = _GET_ACTIVITY.format(activity_id=activity_id)
    return garth.connectapi(endpoint)


def get_activity_weather(activity_id: str) -> dict:
    """Get weather information for a completed activity."""
    endpoint = _GET_ACTIVITY_WEATHER.format(activity_id=activity_id)
    return garth.connectapi(endpoint)


def list_activities(
    limit: int = 20,
    start: int = 0,
    activity_type: str | None = None,
    search: str | None = None,
) -> dict:
    """List completed activities with optional filters."""
    params: dict = {"limit": limit, "start": start}
    if activity_type:
        params["activityType"] = activity_type
    if search:
        params["search"] = search
    return {"activities": garth.connectapi(_LIST_ACTIVITIES, "GET", params=params)}


def schedule_workout(workout_id: str, date: str) -> dict:
    """Schedule a workout on a given date (YYYY-MM-DD)."""
    datetime.strptime(date, "%Y-%m-%d")  # validate
    result = garth.schedule_workout(workout_id, date)
    sid = result.get("workoutScheduleId")
    if sid is None:
        raise RuntimeError(f"Scheduling failed: {result}")
    return {"workoutScheduleId": str(sid)}


def delete_workout(workout_id: str) -> bool:
    """Delete a workout from Garmin Connect."""
    try:
        garth.delete_workout(workout_id)
        logger.info("Deleted workout %s.", workout_id)
        return True
    except Exception as exc:
        logger.error("Failed to delete workout %s: %s", workout_id, exc)
        return False


def upload_workout(workout_data: dict) -> dict:
    """Upload a structured workout to Garmin Connect."""
    result = garth.create_workout(workout_data)
    workout_id = result.get("workoutId")
    if workout_id is None:
        raise RuntimeError("No workout ID returned from Garmin.")
    return {"workoutId": str(workout_id)}
