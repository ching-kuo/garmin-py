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
        assert_row_has_keys(row, ["date", "duration_hours", "score"])
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
