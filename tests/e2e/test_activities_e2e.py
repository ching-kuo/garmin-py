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
def test_get_multisport_activity(run_cli, rate_limiter, cli_runner, garth_session):
    """Fetch a multisport activity and verify child activities are returned."""
    from tests.e2e.conftest import _invoke_cli_json

    # Search for a multisport activity in recent history
    result, parsed = _invoke_cli_json(
        cli_runner, rate_limiter,
        ["activity", "list", "--limit", "50", "--type", "multi_sport"],
    )
    assert_exit_ok(result)
    assert_envelope_ok(parsed)

    if not parsed["data"]:
        pytest.skip("No multisport activities found in account")

    ms_id = parsed["data"][0]["id"]
    result, parsed = run_cli(["activity", "get", str(ms_id)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)

    # The parent row should exist
    assert parsed["count"] >= 1
    parent = parsed["data"][0]
    assert parent["id"] == ms_id

    # If the API returned childIds, the response should include children
    if "children" in parsed:
        children = parsed["children"]
        assert isinstance(children, list)
        assert len(children) >= 1
        for child in children:
            assert_row_has_keys(child, ["id", "sport", "distance_km", "duration_min"])


@pytest.mark.e2e
def test_list_activities_with_date_range(run_cli):
    """List activities filtered by a date range."""
    result, parsed = run_cli([
        "activity", "list", "--limit", "5",
        "--from", "2026-03-01", "--to", "2026-03-31",
    ])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    assert parsed["date_range"] is not None
    assert parsed["date_range"]["from"] == "2026-03-01"
    assert parsed["date_range"]["to"] == "2026-03-31"
    for row in parsed["data"]:
        assert_row_has_keys(row, ["id", "date", "name", "type"])
        if row["date"]:
            assert "2026-03" in row["date"]


@pytest.mark.e2e
def test_list_activities_with_days(run_cli):
    """List activities filtered by --days."""
    result, parsed = run_cli(["activity", "list", "--limit", "5", "--days", "30"])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    assert parsed["date_range"] is not None


@pytest.mark.e2e
def test_get_activity_weather(run_cli, activity_id):
    if activity_id is None:
        pytest.skip("No activities found")
    result, parsed = run_cli(["activity", "weather", str(activity_id)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
