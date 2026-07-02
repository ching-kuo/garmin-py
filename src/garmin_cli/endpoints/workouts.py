"""Workout endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from garmin_cli import backend as garth
from garmin_cli.endpoints._base import (
    _make_request,
    _make_write_request,
    _retry_loop,
    _validate_numeric_id,
)


def _request(url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _make_request(garth.connectapi, url, params=params)


def _write_request(
    url: str,
    *,
    method: str,
    json: dict[str, Any] | None = None,
    capability: str | None = None,
) -> Any:
    if capability is None:
        return _make_write_request(garth.connectapi, method, url, json=json)
    return _make_write_request(
        lambda request_url, **request_kwargs: garth.connectapi(
            request_url,
            capability=capability,
            **request_kwargs,
        ),
        method,
        url,
        json=json,
    )


def _typed_read(
    call: Any,
    *,
    not_found_message: str,
) -> Any:
    return _retry_loop(
        call,
        immediate_errors={
            404: (not_found_message, "NOT_FOUND"),
        },
    )


def _typed_write(call: Any) -> Any:
    return _retry_loop(
        call,
        immediate_errors={
            400: ("Invalid input.", "INVALID_INPUT"),
            401: ("Authentication failed.", "AUTH_FAILED"),
            403: ("Authentication failed.", "AUTH_FAILED"),
            404: ("Not found.", "NOT_FOUND"),
            409: ("Invalid input.", "INVALID_INPUT"),
        },
    )


def list_workouts(limit: int) -> list:
    result = _typed_read(
        lambda: garth.list_workouts(limit),
        not_found_message="Not found: /workout-service/workouts",
    )
    if isinstance(result, dict):
        return [result]
    return result if result is not None else []


def get_workout(workout_id: Any) -> dict:
    validated = _validate_numeric_id(workout_id, "workout_id")
    result = _typed_read(
        lambda: garth.get_workout(validated),
        not_found_message=f"Not found: /workout-service/workout/{validated}",
    )
    return result if result is not None else {}


def create_workout(payload: dict) -> dict:
    """POST /workout-service/workout with Garmin-format payload."""
    return _typed_write(lambda: garth.create_workout(payload))


def update_workout(workout_id: Any, merged_payload: dict) -> None:
    """PUT /workout-service/workout/{id} with pre-merged Garmin-format payload."""
    validated = _validate_numeric_id(workout_id, "workout_id")
    _write_request(
        f"/workout-service/workout/{validated}",
        method="PUT",
        json=merged_payload,
        capability="workout_update",
    )


def delete_workout(workout_id: Any) -> None:
    """DELETE /workout-service/workout/{id}."""
    validated = _validate_numeric_id(workout_id, "workout_id")
    _typed_write(lambda: garth.delete_workout(validated))


def schedule_workout(workout_id: Any, schedule_date: date) -> dict:
    """POST /workout-service/schedule/{id} with date."""
    validated = _validate_numeric_id(workout_id, "workout_id")
    return _typed_write(lambda: garth.schedule_workout(validated, schedule_date))


def unschedule_workout(scheduled_workout_id: Any) -> None:
    """DELETE /workout-service/schedule/{scheduleId}.

    Removes a calendar entry created by :func:`schedule_workout`; the workout
    template itself is preserved. ``scheduled_workout_id`` is the
    ``workoutScheduleId`` returned by scheduling (not the workout id).
    """
    validated = _validate_numeric_id(scheduled_workout_id, "scheduled_workout_id")
    _typed_write(lambda: garth.unschedule_workout(validated))


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
