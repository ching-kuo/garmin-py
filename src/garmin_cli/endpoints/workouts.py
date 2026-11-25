"""Workout endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

from garmin_cli import backend as garth
from garmin_cli.exceptions import GarminCliError
from garmin_cli.workout_schema import calendar_schedule_id
from garmin_cli.endpoints._base import (
    _NOT_FOUND_ERRORS,
    _make_request,
    _make_typed_create,
    _make_typed_delete,
    _make_typed_write,
    _retry_loop,
    _validate_numeric_id,
)

logger = logging.getLogger(__name__)


def _request(url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _make_request(garth.connectapi, url, params=params)


def _typed_read(
    call: Any,
    *,
    not_found_message: str,
) -> Any:
    return _retry_loop(call, immediate_errors={404: (not_found_message, "NOT_FOUND")})


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
    """POST /workout-service/workout with Garmin-format payload (retried only on 429)."""
    return _make_typed_create(garth.create_workout, payload)


def update_workout(workout_id: Any, merged_payload: dict) -> None:
    """PUT /workout-service/workout/{id} with pre-merged Garmin-format payload."""
    validated = _validate_numeric_id(workout_id, "workout_id")
    _make_typed_write(garth.update_workout, validated, merged_payload)


def delete_workout(workout_id: Any) -> None:
    """DELETE /workout-service/workout/{id}."""
    validated = _validate_numeric_id(workout_id, "workout_id")
    _make_typed_delete(garth.delete_workout, validated)


def schedule_workout(workout_id: Any, schedule_date: date) -> dict:
    """POST /workout-service/schedule/{id} with date (retried only on 429)."""
    validated = _validate_numeric_id(workout_id, "workout_id")
    return _make_typed_create(garth.schedule_workout, validated, schedule_date)


def send_workout_to_device(workout_id: Any, workout_name: str | None, device_id: Any) -> None:
    """POST /device-service/devicemessage/messages (retried only on 429/427, refused unprocessed).

    Each accepted call queues another message for the device, so a 5xx or
    network failure is not retried, and its error says the workout may be
    queued (a connection can drop after Garmin accepted the POST).
    """
    validated_workout = _validate_numeric_id(workout_id, "workout_id")
    validated_device = _validate_numeric_id(device_id, "device_id")
    try:
        _make_typed_create(garth.send_workout_message, validated_workout, workout_name, validated_device)
    except GarminCliError as exc:
        if not (exc.may_have_landed or exc.error_code == "NETWORK_ERROR"):
            raise
        raise GarminCliError(
            error=f"{exc.error} The workout may already be queued for the device; check it before sending again.",
            error_code=exc.error_code,
            retry_after_seconds=exc.retry_after_seconds,
            may_have_landed=True,
            local_config=exc.local_config,
            mfa_rejected=exc.mfa_rejected,
        ) from exc


def unschedule_workout(scheduled_workout_id: Any) -> None:
    """DELETE /workout-service/schedule/{scheduleId}.

    Removes a calendar entry created by :func:`schedule_workout`; the workout
    template itself is preserved. ``scheduled_workout_id`` is the
    ``workoutScheduleId`` returned by scheduling (not the workout id).
    """
    validated = _validate_numeric_id(scheduled_workout_id, "scheduled_workout_id")
    _make_typed_delete(garth.unschedule_workout, validated)


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


def _get_scheduled_by_period(start: date, end: date, *, strict: bool = False) -> list[Any]:
    """Scheduled workouts in [start, end], including adaptive-plan sessions.

    Garmin Coach (adaptive) sessions can be missing from the calendar-service
    pages but are listed here (python-garminconnect 0.3.14/0.3.19 notes).
    The lookup is supplemental: it is tried once on server and network errors,
    and if it fails for any reason other than a rate limit or a missing
    session, the calendar pages stand alone, unless *strict* asks for every
    failure to be raised.
    """
    try:
        result = _retry_loop(
            lambda: garth.connectapi(
                "/workout-service/schedule/workoutScheduleByPeriod",
                params={"startDate": start.isoformat(), "endDate": end.isoformat()},
            ),
            immediate_errors=_NOT_FOUND_ERRORS,
            retry_transient=False,
        )
    except Exception as exc:  # includes transport failures (timeouts, resets)
        if strict or (isinstance(exc, GarminCliError) and exc.error_code in {"RATE_LIMITED", "AUTH_MISSING"}):
            raise
        reason = exc.error_code if isinstance(exc, GarminCliError) else type(exc).__name__
        logger.debug("workoutScheduleByPeriod unavailable (%s); calendar only", reason)
        return []
    if strict and not isinstance(result, list) and not _no_content(result):
        raise _unusable("workoutScheduleByPeriod lookup")
    return result if isinstance(result, list) else []


def _no_content(payload: Any) -> bool:
    """An HTTP 204 (an empty period): garminconnect returns {} for it."""
    return payload is None or payload == {}


def _unusable(what: str) -> GarminCliError:
    """A strict calendar read cannot treat an unexpected payload as empty."""
    return GarminCliError(error=f"Garmin {what} returned no item list.", error_code="SERVER_ERROR")


def _in_range(item: Any, start: date, end: date) -> bool:
    item_date = item.get("date") if isinstance(item, dict) else None
    if not isinstance(item_date, str):
        return False
    try:
        return start <= date.fromisoformat(item_date) <= end
    except ValueError:
        return False


def get_calendar_range(start: date, end: date, *, strict: bool = False) -> list:
    """Calendar items in [start, end]; see :func:`get_calendar_range_counted`."""
    return get_calendar_range_counted(start, end, strict=strict)[0]


def get_calendar_range_counted(start: date, end: date, *, strict: bool = False) -> tuple[list, int]:
    """Collect calendarItems week by week, plus schedules the calendar omits.

    Returns the items and the number of requests made (calendar pages plus
    the ``workoutScheduleByPeriod`` lookup; retries are not counted).

    Each page is the calendar week containing the requested day (live: Monday
    to Sunday, with its own ``startDate``/``endDate``); the walk continues from
    the day after the page's ``endDate``. A page without usable bounds advances
    7 days (never skipping a week whatever its first weekday), and the page of
    ``end`` itself is always read, so the walk makes at most ceil(days / 7) + 1
    page reads. Items repeated across pages are kept once by
    ``(itemType, id, date)``; supplemental schedules are skipped when their
    schedule id is already a schedule on the calendar, and the result is
    ordered by date. With *strict*, a failed ``workoutScheduleByPeriod``
    lookup or a page or lookup without a list of items raises instead of
    reading as empty, so callers can trust an absence; a no-content (HTTP
    204) response still reads as empty.
    """
    all_items: list = []
    # Pages overlap only after a page without usable bounds.
    seen: set[tuple[Any, Any, Any]] = set()
    current = start
    pages = 0

    while current <= end:
        url = (
            f"/calendar-service/year/{current.year}/month/{current.month - 1}"
            f"/day/{current.day}/start/1"
        )
        raw_page = _request(url)
        pages += 1
        response = raw_page if isinstance(raw_page, dict) else {}
        page_items = response.get("calendarItems")
        if strict and not isinstance(page_items, list) and not _no_content(raw_page):
            raise _unusable("calendar page")
        for item in page_items if isinstance(page_items, list) else []:
            if not _in_range(item, start, end):
                continue
            # An id-less item can only be recognised as a repeat by its content.
            key = (
                (item.get("itemType"), item.get("id"), item.get("date"))
                if item.get("id") is not None
                else (None, None, json.dumps(item, sort_keys=True, default=str))
            )
            if key in seen:
                continue
            seen.add(key)
            all_items.append(item)
        try:
            page_end: date | None = date.fromisoformat(str(response.get("endDate")))
        except ValueError:
            page_end = None
        if page_end is not None and page_end >= current:
            if page_end >= end:
                break  # before stepping past end (date.max cannot step)
            current = page_end + timedelta(days=1)
        elif current == end:
            break
        else:
            # Unknown coverage: a week holds 7 days, so +7 cannot skip one; end's
            # own page is read last.
            current += timedelta(days=min(7, (end - current).days))

    on_calendar = {schedule_id for item in all_items if (schedule_id := calendar_schedule_id(item)) is not None}
    for entry in _get_scheduled_by_period(start, end, strict=strict):
        if not isinstance(entry, dict) or entry.get("workoutScheduleId") in on_calendar:
            continue
        item = _schedule_as_calendar_item(entry)
        if _in_range(item, start, end):
            all_items.append(item)
            if item["id"] is not None:
                on_calendar.add(item["id"])

    return sorted(all_items, key=lambda item: item["date"]), pages + 1
