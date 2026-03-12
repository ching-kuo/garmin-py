"""E2E tests for workout commands against live Garmin Connect API."""
from __future__ import annotations

import pytest

from tests.e2e.conftest import (
    assert_envelope_ok,
    assert_exit_ok,
    assert_row_has_keys,
    fetch_first_resource_id,
)


@pytest.fixture(scope="module")
def workout_id(request, cli_runner, rate_limiter, garth_session):
    """Fetch the first workout ID for use in tests requiring an ID."""
    if not request.config.getoption("--e2e", default=False):
        return None
    return fetch_first_resource_id(cli_runner, rate_limiter, "workout")


@pytest.mark.e2e
def test_list_workouts(run_cli):
    result, parsed = run_cli(["workout", "list", "--limit", "3"])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if parsed["data"]:
        row = parsed["data"][0]
        assert_row_has_keys(row, ["id", "name"])


@pytest.mark.e2e
def test_get_workout_by_id(run_cli, workout_id):
    if workout_id is None:
        pytest.skip("No workouts found")
    result, parsed = run_cli(["workout", "get", str(workout_id)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)


@pytest.mark.e2e
def test_calendar_7_days(run_cli):
    result, parsed = run_cli(["workout", "calendar", "--days", "7"])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
