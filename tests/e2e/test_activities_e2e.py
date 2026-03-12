"""E2E tests for activity commands against live Garmin Connect API."""
from __future__ import annotations

import pytest

from tests.e2e.conftest import (
    assert_envelope_ok,
    assert_exit_ok,
    assert_row_has_keys,
    fetch_first_resource_id,
)


@pytest.fixture(scope="module")
def activity_id(request, cli_runner, rate_limiter, garth_session):
    """Fetch the first activity ID for use in tests requiring an ID."""
    if not request.config.getoption("--e2e", default=False):
        return None
    return fetch_first_resource_id(cli_runner, rate_limiter, "activity")


@pytest.mark.e2e
def test_list_activities_default(run_cli):
    result, parsed = run_cli(["activity", "list", "--limit", "3"])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if parsed["data"]:
        row = parsed["data"][0]
        assert_row_has_keys(row, ["id", "date", "name", "type"])
        assert isinstance(row["id"], (int, str))
        assert isinstance(row["date"], str)


@pytest.mark.e2e
def test_list_activities_with_type_filter(run_cli):
    result, parsed = run_cli(["activity", "list", "--limit", "3", "--type", "running"])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if parsed["data"]:
        for row in parsed["data"]:
            assert "running" in row["type"].lower()


@pytest.mark.e2e
def test_get_activity_by_id(run_cli, activity_id):
    if activity_id is None:
        pytest.skip("No activities found")
    result, parsed = run_cli(["activity", "get", str(activity_id)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)


@pytest.mark.e2e
def test_get_activity_weather(run_cli, activity_id):
    if activity_id is None:
        pytest.skip("No activities found")
    result, parsed = run_cli(["activity", "weather", str(activity_id)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
