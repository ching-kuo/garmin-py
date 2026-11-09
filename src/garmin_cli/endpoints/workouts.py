"""Workout endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from garmin_cli import backend as garth
from garmin_cli.exceptions import GarminCliError
from garmin_cli.endpoints._base import (
    _AUTH_NOT_FOUND_ERRORS,
    _make_request,
    _retry_loop,
    _validate_numeric_id,
)

logger = logging.getLogger(__name__)

# Supplemental lookups fail fast on server errors instead of sleeping through
# the full retry schedule; only 429s are retried.
_FAIL_FAST_ERRORS = {
    **_AUTH_NOT_FOUND_ERRORS,
    **{status: ("Garmin API server error.", "SERVER_ERROR") for status in (500, 502, 503, 504)},
}


def _request(url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _make_request(garth.connectapi, url, params=params)


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
    _typed_write(lambda: garth.update_workout(validated, merged_payload))


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


def _schedule_as_calendar_item(entry: dict[str, Any]) -> dict[str, Any]:
    """Map a ``workoutScheduleByPeriod`` entry onto the calendar-item keys."""
    workout = entry.get("workout")
    workout = workout if isinstance(workout, dict) else {}
    sport = workout.get("sportType")
    sport = sport if isinstance(sport, dict) else {}
    return {
        "id": entry.get("workoutScheduleId"),
        "itemType": "workout",
        "date": entry.get("calendarDate"),
        "workoutId": workout.get("workoutId"),
        "title": workout.get("workoutName"),
        "sportTypeKey": sport.get("sportTypeKey"),
        "trainingPlanId": workout.get("trainingPlanId"),
        "atpPlanId": workout.get("atpPlanId"),
    }


def _get_scheduled_by_period(start: date, end: date) -> list[Any]:
    """Scheduled workouts in [start, end], including adaptive-plan sessions.

    Garmin Coach (adaptive) sessions can be missing from the calendar-service
    pages but are listed here (python-garminconnect 0.3.14/0.3.19 notes).
    The lookup is supplemental: it is tried once on server errors, and if it
    fails for any reason other than a rate limit or a missing session, the
    calendar pages stand alone.
    """
    try:
        result = _retry_loop(
            lambda: garth.connectapi(
                "/workout-service/schedule/workoutScheduleByPeriod",
                params={"startDate": start.isoformat(), "endDate": end.isoformat()},
            ),
            immediate_errors=_FAIL_FAST_ERRORS,
        )
    except Exception as exc:  # includes transport failures (timeouts, resets)
        if isinstance(exc, GarminCliError) and exc.error_code in {"RATE_LIMITED", "AUTH_MISSING"}:
            raise
        reason = exc.error_code if isinstance(exc, GarminCliError) else type(exc).__name__
        logger.debug("workoutScheduleByPeriod unavailable (%s); calendar only", reason)
        return []
    return result if isinstance(result, list) else []


def _in_range(item: Any, start: date, end: date) -> bool:
    item_date = item.get("date") if isinstance(item, dict) else None
    if not isinstance(item_date, str):
        return False
    try:
        return start <= date.fromisoformat(item_date) <= end
    except ValueError:
        return False


def get_calendar_range(start: date, end: date) -> list:
    """Collect calendarItems week by week, plus schedules the calendar omits.

    Costs one request per calendar week plus one ``workoutScheduleByPeriod``
    request. Merged schedules are deduplicated by schedule id (a calendar
    workout item's ``id``) and the result is ordered by date.
    """
    all_items: list = []
    current = start

    while current <= end:
        url = (
            f"/calendar-service/year/{current.year}/month/{current.month - 1}"
            f"/day/{current.day}/start/1"
        )
        response = _request(url)
        if isinstance(response, dict):
            all_items.extend(
                item for item in response.get("calendarItems", []) if _in_range(item, start, end)
            )
        current = current + timedelta(days=7)

    on_calendar = {item.get("id") for item in all_items}
    for entry in _get_scheduled_by_period(start, end):
        if not isinstance(entry, dict) or entry.get("workoutScheduleId") in on_calendar:
            continue
        item = _schedule_as_calendar_item(entry)
        if _in_range(item, start, end):
            all_items.append(item)

    return sorted(all_items, key=lambda item: item["date"])
