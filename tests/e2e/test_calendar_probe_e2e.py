"""Explicitly gated live probe for Garmin calendar identifiers.

The maintainer runs this test with both ``--e2e`` and ``--e2e-writes``.
It creates, schedules, unschedules, and deletes one temporary workout.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable

import pytest

from garmin_cli.auth import ensure_authenticated
from garmin_cli.config import CliConfig
from garmin_cli.endpoints.workouts import (
    create_workout,
    delete_workout,
    get_calendar_range,
    get_workout,
    schedule_workout,
    unschedule_workout,
)
from garmin_cli.serializers import serialize_calendar_workout
from garmin_cli.workout_builder import build_garmin_payload

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_writes]


def _live_call(rate_limiter: Any, call: Callable[[], Any]) -> Any:
    rate_limiter.wait()
    try:
        return call()
    finally:
        rate_limiter.mark_complete()


def _numeric_field(payload: Any, *names: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    for name in names:
        value = payload.get(name)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def test_live_calendar_workout_and_schedule_identifier_probe(
    garth_session: str,
    rate_limiter: Any,
) -> None:
    ensure_authenticated(CliConfig(garth_home=garth_session))
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = build_garmin_payload({
        "name": f"__e2e_calendar_identifier_probe_{suffix}",
        "sport": "running",
        "steps": [{
            "type": "warmup",
            "duration": {"type": "time", "value": 300},
            "target": {"type": "no.target"},
        }],
    })
    schedule_date = date.today() + timedelta(days=330)
    workout_id: int | None = None
    schedule_id: int | None = None
    primary_error: BaseException | None = None
    cleanup_errors: list[str] = []

    try:
        created = _live_call(rate_limiter, lambda: create_workout(payload))
        workout_id = _numeric_field(created, "workoutId", "id")
        assert workout_id is not None, "create response lacks an integer workout id field"

        scheduled = _live_call(
            rate_limiter,
            lambda: schedule_workout(workout_id, schedule_date),
        )
        # Verified live 2026-07-27: the schedule response carries
        # workoutScheduleId; calendar items do NOT — their schedule id is the
        # plain ``id`` field.
        schedule_id = _numeric_field(scheduled, "workoutScheduleId")
        assert schedule_id is not None, (
            "schedule response lacks an integer workoutScheduleId field"
        )
        raw_items = _live_call(
            rate_limiter,
            lambda: get_calendar_range(schedule_date, schedule_date),
        )
        matching = [
            item
            for item in raw_items
            if isinstance(item, dict) and item.get("workoutId") == workout_id
        ]
        assert len(matching) == 1, (
            "calendar probe expected one item selected by workoutId field and integer type"
        )
        raw_item = matching[0]
        assert "workoutScheduleId" not in raw_item, (
            "calendar item unexpectedly grew a workoutScheduleId field - "
            "re-verify the serializer fallback contract"
        )
        assert _numeric_field(raw_item, "id") == schedule_id, (
            "calendar item id does not match the schedule response workoutScheduleId"
        )

        serialized = serialize_calendar_workout({"calendarItems": [raw_item]})
        assert len(serialized) == 1, "calendar serializer did not return one row"
        assert serialized[0]["workout_id"] == raw_item["workoutId"], (
            "serialized workout_id does not match raw workoutId field"
        )
        assert serialized[0]["workout_schedule_id"] == schedule_id, (
            "serialized workout_schedule_id does not match the live schedule id"
        )
    except Exception as exc:  # cleanup must run for partial writes
        primary_error = exc
    finally:
        if workout_id is not None and schedule_id is None:
            try:
                raw_items = _live_call(
                    rate_limiter,
                    lambda: get_calendar_range(schedule_date, schedule_date),
                )
                schedule_id = next(
                    (
                        candidate
                        for item in raw_items
                        if isinstance(item, dict) and item.get("workoutId") == workout_id
                        if (
                            candidate := _numeric_field(item, "workoutScheduleId", "id")
                        ) is not None
                    ),
                    None,
                )
            except Exception as exc:
                cleanup_errors.append(f"calendar lookup: {type(exc).__name__}: {exc}")
        if schedule_id is not None:
            try:
                _live_call(
                    rate_limiter,
                    lambda: unschedule_workout(schedule_id),
                )
            except Exception as exc:
                cleanup_errors.append(f"unschedule: {type(exc).__name__}: {exc}")
        if workout_id is not None:
            try:
                preserved = _live_call(
                    rate_limiter,
                    lambda: get_workout(workout_id),
                )
                assert _numeric_field(preserved, "workoutId", "id") == workout_id, (
                    "workout template was not readable after unscheduling"
                )
            except Exception as exc:
                cleanup_errors.append(f"post-unschedule read: {type(exc).__name__}: {exc}")
            try:
                _live_call(
                    rate_limiter,
                    lambda: delete_workout(workout_id),
                )
            except Exception as exc:
                cleanup_errors.append(f"delete: {type(exc).__name__}: {exc}")

    if primary_error is not None or cleanup_errors:
        parts = []
        if primary_error is not None:
            parts.append(f"probe: {type(primary_error).__name__}: {primary_error}")
        parts.extend(cleanup_errors)
        pytest.fail("calendar identifier probe errors: " + "; ".join(parts))
