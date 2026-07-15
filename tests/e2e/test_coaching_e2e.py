"""E2E tests for coaching and training-plan read tools against the live API.

Read-only by design: coach_snapshot, training_plan_reconcile, and
training_plan_preview never write to Garmin Connect.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.config import CliConfig
from garmin_cli.mcp_server import create_mcp_server
from tests.e2e.test_mcp_e2e import _call_tool_json

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def mcp_server_live(garth_session):
    return create_mcp_server(CliConfig(garth_home=garth_session))

_SNAPSHOT_STATES = {
    "completed_exact",
    "completed_inferred",
    "ambiguous",
    "skipped",
    "planned_future",
    "unplanned_activity",
}


@pytest.mark.e2e
def test_coach_snapshot_live_defaults(mcp_server_live, rate_limiter):
    snapshot = _call_tool_json(mcp_server_live, rate_limiter, "coach_snapshot", extra_delay=5.0)

    for key in (
        "complete",
        "aborted",
        "as_of",
        "baseline",
        "recovery",
        "load",
        "plan",
        "wellness",
        "execution",
        "provenance",
    ):
        assert key in snapshot, f"missing snapshot key: {key}"
    assert snapshot["aborted"] is False
    assert snapshot["errors"] == []
    # complete=false is legitimate when the account's device lacks a feature
    # (e.g. training readiness 404s); it must then be explained in unavailable.
    if not snapshot["complete"]:
        assert snapshot["unavailable"], "incomplete snapshot with no unavailable sections"

    provenance = snapshot["provenance"]
    assert provenance["estimated_requests"] <= 30
    assert 0 < provenance["completed_requests"] <= provenance["estimated_requests"]

    baseline = snapshot["baseline"]
    assert baseline["days"] == 28
    assert baseline["to"] == (date.today() - timedelta(days=1)).isoformat()

    signals = snapshot["recovery"]["signals"]
    assert isinstance(signals, list) and signals
    for row in signals:
        if row.get("baseline_from") is None:
            continue
        # Daily signals must report their shorter (9-day) window, not the
        # 28-day baseline window.
        expected_days = 9 if row["signal"] in {"resting_heart_rate", "stress"} else 28
        assert row["baseline_from"] == (
            date.today() - timedelta(days=expected_days)
        ).isoformat(), row["signal"]

    plan = snapshot["plan"]
    for row in plan["next_7_days"]:
        row_date = date.fromisoformat(row["date"])
        assert date.today() <= row_date <= date.today() + timedelta(days=6)

    wellness = snapshot["wellness"]
    for section in ("training_readiness", "spo2", "steps", "weight"):
        assert isinstance(wellness[section], list)


@pytest.mark.e2e
def test_training_plan_reconcile_live(mcp_server_live, rate_limiter):
    end = date.today()
    start = end - timedelta(days=13)
    result = _call_tool_json(
        mcp_server_live,
        rate_limiter,
        "training_plan_reconcile",
        {"start_date": start.isoformat(), "end_date": end.isoformat()},
        extra_delay=5.0,
    )

    assert set(result) >= {"entries", "provenance"}
    provenance = result["provenance"]
    assert provenance["detail"] == "summary"
    assert provenance["detail_requests"] <= provenance["activities_examined"]

    for entry in result["entries"]:
        assert entry["state"] in _SNAPSHOT_STATES
        if entry["state"] == "completed_exact":
            assert entry["match_method"] == "workout_id"
        if entry["state"] == "unplanned_activity":
            assert entry["planned"] is None


@pytest.mark.e2e
def test_training_plan_preview_live_is_read_only(mcp_server_live, rate_limiter):
    workouts = _call_tool_json(
        mcp_server_live, rate_limiter, "workout_list", {"limit": 1}
    )
    if not workouts["rows"]:
        pytest.skip("no workout templates available for preview")
    workout_id = workouts["rows"][0]["id"]

    target = date.today() + timedelta(days=21)
    plan: dict[str, Any] = {
        "name": "e2e preview probe",
        "start_date": target.isoformat(),
        "end_date": target.isoformat(),
        "entries": [
            {"entry_id": "probe-1", "date": target.isoformat(), "workout_id": workout_id}
        ],
    }
    preview = _call_tool_json(
        mcp_server_live, rate_limiter, "training_plan_preview", {"plan": plan}
    )

    assert set(preview) >= {"complete", "operations", "errors", "conflicts", "summary"}
    assert preview["errors"] == []
    if preview["complete"]:
        ops = preview["operations"]
        assert len(ops) == 1
        assert ops[0]["action"] == "schedule"
        assert ops[0]["state"] == "planned"
        assert ops[0]["date"] == target.isoformat()
    else:
        # A real occupant on the target date is legitimate live state.
        assert all(c["reason"] == "destination_occupied" for c in preview["conflicts"])

    # Preview must not have written anything: the target date stays as it was.
    calendar = _call_tool_json(
        mcp_server_live,
        rate_limiter,
        "training_plan_reconcile",
        {"start_date": target.isoformat(), "end_date": target.isoformat()},
        extra_delay=5.0,
    )
    planned = [row for row in calendar["entries"] if row["planned"] is not None]
    if preview["complete"]:
        # Destination was free during preview; it must still be free afterwards.
        assert planned == []
