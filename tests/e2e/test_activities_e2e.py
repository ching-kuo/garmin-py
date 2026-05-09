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


@pytest.mark.e2e
def test_get_activity_detail_union_schema_and_manifest(run_cli, activity_id):
    """activity get --detail returns the full union schema with sport-applicable
    keys populated and inapplicable keys present as null. When unavailable is
    present, every entry must declare a recognised reason."""
    if activity_id is None:
        pytest.skip("No activities found")
    result, parsed = run_cli(["activity", "get", "--detail", str(activity_id)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if not parsed["data"]:
        pytest.skip("No detail row returned")

    row = parsed["data"][0]
    # Union schema covers cycling, running, and swim metric families. Whether or
    # not the watch recorded these, the keys must be present so consumers see a
    # stable shape.
    union_keys = [
        "norm_power_w", "intensity_factor", "training_stress_score",
        "avg_ground_contact_time", "avg_vertical_oscillation",
        "avg_vertical_ratio", "avg_stride_length",
        "swolf", "total_strokes", "avg_stroke_rate", "avg_distance_per_stroke",
        "aerobic_training_effect", "anaerobic_training_effect",
        "vo2_max_value", "recovery_time_hours",
    ]
    assert_row_has_keys(row, union_keys)

    if "unavailable" in parsed:
        manifest = parsed["unavailable"]
        assert isinstance(manifest, list)
        for entry in manifest:
            assert_row_has_keys(entry, ["key", "reason"])
            assert entry["reason"] in {
                "not_applicable_to_sport", "absent_in_response",
            }


@pytest.mark.e2e
def test_get_activity_with_laps_flag(run_cli, activity_id):
    """activity get --laps adds a laps[] envelope alongside detail data."""
    if activity_id is None:
        pytest.skip("No activities found")
    result, parsed = run_cli(["activity", "get", "--detail", "--laps", str(activity_id)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    assert "laps" in parsed, "Missing 'laps' key when --laps is set"
    assert isinstance(parsed["laps"], list)
    if parsed["laps"]:
        lap = parsed["laps"][0]
        assert_row_has_keys(lap, ["lap_index", "duration_min", "distance_km"])


@pytest.mark.e2e
def test_activity_laps_subcommand(run_cli, activity_id):
    """activity laps returns lap rows; multisport activities stamp leg_index."""
    if activity_id is None:
        pytest.skip("No activities found")
    result, parsed = run_cli(["activity", "laps", str(activity_id)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if parsed["data"]:
        row = parsed["data"][0]
        assert_row_has_keys(row, ["lap_index", "duration_min", "distance_km"])


@pytest.mark.e2e
def test_activity_zones_subcommand(run_cli, activity_id):
    """activity zones returns time-in-zone breakdown rows."""
    if activity_id is None:
        pytest.skip("No activities found")
    result, parsed = run_cli(["activity", "zones", str(activity_id)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if parsed["data"]:
        row = parsed["data"][0]
        assert_row_has_keys(
            row,
            ["zone", "zone_low_bpm", "zone_high_bpm", "minutes_in_zone"],
        )


@pytest.mark.e2e
def test_multisport_laps_fan_out(run_cli, rate_limiter, cli_runner, garth_session):
    """For multisport parents, activity laps fans out to each child leg and
    stamps a 0-based leg_index on every row."""
    from tests.e2e.conftest import _invoke_cli_json

    result, parsed = _invoke_cli_json(
        cli_runner, rate_limiter,
        ["activity", "list", "--limit", "50", "--type", "multi_sport"],
    )
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if not parsed["data"]:
        pytest.skip("No multisport activities found in account")

    ms_id = parsed["data"][0]["id"]
    result, parsed = run_cli(["activity", "laps", str(ms_id)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if not parsed["data"]:
        pytest.skip("Multisport parent has no lap rows from any leg")

    leg_indices = {row.get("leg_index") for row in parsed["data"]}
    assert all(isinstance(i, int) for i in leg_indices), (
        "Multisport laps must stamp integer leg_index on every row"
    )
    assert min(leg_indices) == 0, "leg_index is 0-based"
