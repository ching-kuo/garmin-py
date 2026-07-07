"""E2E tests for health commands against live Garmin Connect API."""
from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from tests.e2e.conftest import (
    assert_envelope_ok,
    assert_exit_ok,
    assert_numeric_or_none,
    assert_row_has_keys,
)


@pytest.mark.e2e
def test_sleep_today(run_cli):
    result, parsed = run_cli(["health", "sleep", "--days", "1"])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if parsed["data"]:
        row = parsed["data"][0]
        assert_row_has_keys(row, ["date", "bedtime", "wake_time", "duration_hours", "score"])
        assert isinstance(row["date"], str)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"])
        assert_numeric_or_none(row["duration_hours"], "duration_hours")
        assert_numeric_or_none(row["score"], "score")


@pytest.mark.e2e
def test_hrv_today(run_cli):
    result, parsed = run_cli(["health", "hrv", "--days", "1"])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if parsed["data"]:
        row = parsed["data"][0]
        assert_row_has_keys(row, ["date", "weekly_avg", "last_night", "status"])
        assert_numeric_or_none(row["weekly_avg"], "weekly_avg")
        assert_numeric_or_none(row["last_night"], "last_night")
        assert isinstance(row["status"], str) or row["status"] is None


@pytest.mark.e2e
def test_weight_7_days(run_cli):
    result, parsed = run_cli(["health", "weight", "--days", "7"])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if parsed["data"]:
        row = parsed["data"][0]
        assert_row_has_keys(row, ["date", "weight_kg"])
        assert_numeric_or_none(row["weight_kg"], "weight_kg")


@pytest.mark.e2e
def test_sleep_date_range(run_cli):
    today = date.today()
    week_ago = today - timedelta(days=7)
    result, parsed = run_cli(
        ["health", "sleep", "--from", str(week_ago), "--to", str(today)]
    )
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    assert "date_range" in parsed
    if parsed["date_range"] is not None:
        assert isinstance(parsed["date_range"], dict), "date_range is not a dict"
        assert "from" in parsed["date_range"]
        assert "to" in parsed["date_range"]
        assert isinstance(parsed["date_range"]["from"], str)
        assert isinstance(parsed["date_range"]["to"], str)


@pytest.mark.e2e
def test_hrv_single_date(run_cli):
    today = date.today()
    result, parsed = run_cli(["health", "hrv", "--date", str(today)])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)


@pytest.mark.e2e
def test_body_battery_range(run_cli):
    """body-battery rows expose start/end/max levels; when all are non-null the
    intraday peak must be at least the start and end levels."""
    today = date.today()
    week_ago = today - timedelta(days=7)
    result, parsed = run_cli(
        ["health", "body-battery", "--from", str(week_ago), "--to", str(today)]
    )
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
    if not parsed["data"]:
        pytest.skip("No body battery data for the window")
    for row in parsed["data"]:
        assert_row_has_keys(row, ["date", "start_level", "end_level", "max_level"])
        assert_numeric_or_none(row["start_level"], "start_level")
        assert_numeric_or_none(row["end_level"], "end_level")
        assert_numeric_or_none(row["max_level"], "max_level")
        if row["start_level"] is not None and row["end_level"] is not None and row["max_level"] is not None:
            assert row["max_level"] >= max(row["start_level"], row["end_level"]), (
                "intraday peak must be >= start and end levels"
            )
