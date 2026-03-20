"""E2E tests for workout CRUD operations against live Garmin Connect API."""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from tests.e2e.conftest import assert_envelope_ok, assert_exit_ok


MINIMAL_WORKOUT: dict = {
    "name": "__test_garmin_cli_e2e",
    "sport": "running",
    "steps": [
        {
            "type": "warmup",
            "duration": {"type": "time", "value": 300},
            "target": {"type": "no.target"},
        }
    ],
}


@pytest.mark.e2e
def test_workout_create_schedule_delete(run_cli: Any, tmp_path: Any) -> None:
    """Full CRUD flow: create -> verify -> schedule -> delete."""
    unique_name = f"__test_garmin_cli_{uuid.uuid4().hex[:8]}"
    workout_data = {**MINIMAL_WORKOUT, "name": unique_name}

    workout_file = tmp_path / "workout.json"
    workout_file.write_text(json.dumps(workout_data))

    created_id = None
    try:
        # Create
        result, parsed = run_cli(["workout", "create", str(workout_file)])
        assert_exit_ok(result)
        assert_envelope_ok(parsed)
        created_id = parsed["data"][0].get("id") or parsed["data"][0].get("workoutId")
        assert created_id is not None

        # Schedule for tomorrow
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        result, parsed = run_cli(["workout", "schedule", str(created_id), tomorrow])
        assert_exit_ok(result)
        assert_envelope_ok(parsed)
    finally:
        if created_id:
            result, parsed = run_cli(
                ["workout", "delete", str(created_id), "--confirm"]
            )
            assert_exit_ok(result)


@pytest.mark.e2e
def test_workout_create_update_delete(run_cli: Any, tmp_path: Any) -> None:
    """CRUD flow: create -> update name -> delete."""
    unique_name = f"__test_garmin_cli_{uuid.uuid4().hex[:8]}"
    workout_data = {**MINIMAL_WORKOUT, "name": unique_name}

    workout_file = tmp_path / "workout.json"
    workout_file.write_text(json.dumps(workout_data))

    created_id = None
    try:
        # Create
        result, parsed = run_cli(["workout", "create", str(workout_file)])
        assert_exit_ok(result)
        assert_envelope_ok(parsed)
        created_id = parsed["data"][0].get("id") or parsed["data"][0].get("workoutId")
        assert created_id is not None

        # Update name
        updated_name = f"__test_garmin_cli_updated_{uuid.uuid4().hex[:8]}"
        update_data = {"name": updated_name}
        update_file = tmp_path / "update.json"
        update_file.write_text(json.dumps(update_data))

        result, parsed = run_cli(["workout", "update", str(created_id), str(update_file)])
        assert_exit_ok(result)
        assert_envelope_ok(parsed)
    finally:
        if created_id:
            result, parsed = run_cli(
                ["workout", "delete", str(created_id), "--confirm"]
            )
            assert_exit_ok(result)


@pytest.mark.e2e
def test_workout_create_returns_workout_id(run_cli: Any, tmp_path: Any) -> None:
    """Verify create returns a valid numeric workout ID."""
    unique_name = f"__test_garmin_cli_{uuid.uuid4().hex[:8]}"
    workout_data = {**MINIMAL_WORKOUT, "name": unique_name}

    workout_file = tmp_path / "workout.json"
    workout_file.write_text(json.dumps(workout_data))

    created_id = None
    try:
        result, parsed = run_cli(["workout", "create", str(workout_file)])
        assert_exit_ok(result)
        assert_envelope_ok(parsed)
        assert len(parsed["data"]) == 1
        row = parsed["data"][0]
        workout_id = row.get("id") or row.get("workoutId")
        assert workout_id is not None
        assert isinstance(workout_id, int)
        created_id = workout_id
    finally:
        if created_id:
            run_cli(["workout", "delete", str(created_id), "--confirm"])


@pytest.mark.e2e
def test_workout_delete_nonexistent_returns_error(run_cli: Any) -> None:
    """Deleting a non-existent workout should return an error.

    Garmin returns 403 (AUTH_FAILED) rather than 404 for workout IDs that
    don't belong to the authenticated user, so we accept either error code.
    """
    result, parsed = run_cli(["workout", "delete", "999999999", "--confirm"])
    assert result.exit_code == 1
    assert parsed is not None
    assert parsed.get("ok") is False
    assert parsed.get("error_code") in ("NOT_FOUND", "AUTH_FAILED")


@pytest.mark.e2e
def test_workout_schedule_returns_schedule_id(run_cli: Any, tmp_path: Any) -> None:
    """Verify schedule returns a workoutScheduleId."""
    unique_name = f"__test_garmin_cli_{uuid.uuid4().hex[:8]}"
    workout_data = {**MINIMAL_WORKOUT, "name": unique_name}

    workout_file = tmp_path / "workout.json"
    workout_file.write_text(json.dumps(workout_data))

    created_id = None
    try:
        result, parsed = run_cli(["workout", "create", str(workout_file)])
        assert_exit_ok(result)
        created_id = parsed["data"][0].get("id") or parsed["data"][0].get("workoutId")

        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        result, parsed = run_cli(["workout", "schedule", str(created_id), tomorrow])
        assert_exit_ok(result)
        assert_envelope_ok(parsed)
        row = parsed["data"][0]
        schedule_id = row.get("workoutScheduleId") or row.get("id")
        assert schedule_id is not None
    finally:
        if created_id:
            run_cli(["workout", "delete", str(created_id), "--confirm"])
