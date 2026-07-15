"""MCP boundary tests for bounded reconciliation."""
from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


def test_reconciliation_fetches_detail_for_every_examined_activity(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_calendar_range",
        return_value=[{"date": "2026-07-10", "workoutId": 10, "workoutTypeKey": "running"}],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.list_activities",
        return_value=[
            {"activityId": 1, "startTimeLocal": "2026-07-10T08:00:00", "activityType": {"typeKey": "running"}},
            {"activityId": 2, "startTimeLocal": "2026-07-10T09:00:00", "activityType": {"typeKey": "running"}},
        ],
    )
    detail = mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_activity",
        side_effect=[
            {"activityId": 1, "startTimeLocal": "2026-07-10T08:00:00", "activityType": {"typeKey": "running"}, "metadataDTO": {"associatedWorkoutId": 10}},
            {"activityId": 2, "startTimeLocal": "2026-07-10T09:00:00", "activityType": {"typeKey": "running"}, "metadataDTO": {}},
        ],
    )
    server = create_mcp_server(_config())

    result = _call(server, "training_plan_reconcile", {"start_date": "2026-07-01", "end_date": "2026-07-14"})

    assert detail.call_count == 2
    assert result["entries"][0]["state"] == "completed_exact"
    assert result["provenance"] == {
        "activities_examined": 2,
        "detail_requests": 2,
        "max_activities": 50,
        "truncated": False,
        "detail": "summary",
    }
