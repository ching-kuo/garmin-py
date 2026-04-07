"""Workout endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import garth

from garmin_cli.endpoints._base import _make_request, _make_write_request, _validate_numeric_id
from garmin_cli.exceptions import GarminCliError


def _request(url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _make_request(garth.connectapi, url, params=params)


def _write_request(url: str, *, method: str, json: dict[str, Any] | None = None) -> Any:
    return _make_write_request(garth.connectapi, method, url, json=json)


def list_workouts(limit: int) -> list:
    result = _request(
        "/workout-service/workouts",
        params={"start": 0, "limit": limit},
    )
    if isinstance(result, dict):
        return [result]
    return result if result is not None else []


def get_workout(workout_id: Any) -> dict:
    validated = _validate_numeric_id(workout_id, "workout_id")
    result = _request(f"/workout-service/workout/{validated}")
    return result if result is not None else {}


def create_workout(payload: dict) -> dict:
    """POST /workout-service/workout with Garmin-format payload."""
    return _write_request("/workout-service/workout", method="POST", json=payload)


def update_workout(workout_id: Any, merged_payload: dict) -> None:
    """PUT /workout-service/workout/{id} with pre-merged Garmin-format payload."""
    validated = _validate_numeric_id(workout_id, "workout_id")
    _write_request(f"/workout-service/workout/{validated}", method="PUT", json=merged_payload)


def delete_workout(workout_id: Any) -> None:
    """DELETE /workout-service/workout/{id}."""
    validated = _validate_numeric_id(workout_id, "workout_id")
    _write_request(f"/workout-service/workout/{validated}", method="DELETE")


def schedule_workout(workout_id: Any, schedule_date: date) -> dict:
    """POST /workout-service/schedule/{id} with date."""
    validated = _validate_numeric_id(workout_id, "workout_id")
    return _write_request(
        f"/workout-service/schedule/{validated}",
        method="POST",
        json={"date": schedule_date.isoformat()},
    )


def get_calendar_range(start: date, end: date) -> list:
    """Iterate week by week from start to end, collecting calendarItems."""
    all_items: list = []
    current = start

    while current <= end:
        url = (
            f"/calendar-service/year/{current.year}/month/{current.month - 1}"
            f"/day/{current.day}/start/1"
        )
        response = _request(url)
        if isinstance(response, dict):
            items = response.get("calendarItems", [])
            for item in items:
                item_date = item.get("date") if isinstance(item, dict) else None
                if not item_date:
                    continue
                try:
                    parsed_date = date.fromisoformat(item_date)
                except ValueError:
                    continue
                if start <= parsed_date <= end:
                    all_items.append(item)
        current = current + timedelta(days=7)

    return all_items
