"""E2E tests for performance commands against live Garmin Connect API."""
from __future__ import annotations

import pytest

from tests.e2e.conftest import (
    assert_envelope_ok,
    assert_exit_ok,
)


@pytest.mark.e2e
def test_vo2max(run_cli):
    result, parsed = run_cli(["performance", "vo2max"])
    assert_exit_ok(result)
    assert_envelope_ok(parsed)


@pytest.mark.e2e
def test_zones(run_cli):
    result, parsed = run_cli(["performance", "zones"])

    if result.exit_code == 0:
        assert_envelope_ok(parsed)
    elif result.exit_code == 1:
        assert parsed is not None, "Could not parse error response as JSON"
        assert parsed.get("error_code") == "NOT_FOUND", (
            f"Unexpected error_code: {parsed.get('error_code')}"
        )
    else:
        pytest.fail(f"Unexpected exit code: {result.exit_code}")


@pytest.mark.e2e
def test_thresholds(run_cli):
    result, parsed = run_cli(["performance", "thresholds"], extra_delay=10.0)
    assert_exit_ok(result)
    assert_envelope_ok(parsed)
