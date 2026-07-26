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


def test_targets_mode_fetches_bounded_stream_only_when_laps_cannot_answer(
    mocker: Any,
) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_calendar_range",
        return_value=[
            {
                "date": "2026-07-10",
                "workoutId": 10,
                "workoutTypeKey": "running",
            }
        ],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.list_activities",
        return_value=[{
            "activityId": 1,
            "startTimeLocal": "2026-07-10T08:00:00",
            "activityType": {"typeKey": "running"},
        }],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_activity",
        return_value={
            "activityId": 1,
            "startTimeLocal": "2026-07-10T08:00:00",
            "activityType": {"typeKey": "running"},
            "metadataDTO": {"associatedWorkoutId": 10},
        },
    )
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_workout",
        return_value={
            "workoutId": 10,
            "workoutName": "Pace",
            "sportType": {"sportTypeKey": "running"},
            "workoutSegments": [{
                "segmentOrder": 1,
                "sportType": {"sportTypeKey": "running"},
                "workoutSteps": [{
                    "stepOrder": 1,
                    "stepType": {"stepTypeKey": "interval"},
                    "endCondition": {"conditionTypeKey": "time"},
                    "endConditionValue": 600,
                    "targetType": {"workoutTargetTypeKey": "speed.zone"},
                    "targetValueOne": 2.5,
                    "targetValueTwo": 3.5,
                }],
            }],
        },
    )
    mocker.patch("garmin_cli.mcp_tools.coaching.get_activity_splits", return_value={})
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_activity_hr_in_timezones",
        return_value=[],
    )
    stream = mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_activity_details",
        return_value={
            "metricDescriptors": [{
                "key": "directSpeed",
                "metricsIndex": 0,
                "unit": {"key": "mps"},
            }],
            "activityDetailMetrics": [
                {"metrics": [3.0]},
                {"metrics": [4.0]},
            ],
        },
    )
    server = create_mcp_server(_config())

    result = _call(
        server,
        "training_plan_reconcile",
        {
            "start_date": "2026-07-01",
            "end_date": "2026-07-14",
            "detail": "targets",
        },
    )

    stream.assert_called_once_with(1)
    comparison = result["entries"][0]["target_comparison"]
    assert comparison["targets"][0]["time_in_band_pct"] == 50.0
    assert comparison["targets"][0]["quality"] == "sampled_stream"
    assert result["provenance"]["stream_requests"] == 1
    assert result["provenance"]["sample_budget"] == 1000


def test_targets_mode_reports_stream_limit_without_fetching_samples(
    mocker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("garmin_cli.mcp_tools.coaching.TARGET_STREAM_LIMIT", 0)
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_calendar_range",
        return_value=[{
            "date": "2026-07-10",
            "workoutId": 10,
            "workoutTypeKey": "running",
        }],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.list_activities",
        return_value=[{
            "activityId": 1,
            "startTimeLocal": "2026-07-10T08:00:00",
            "activityType": {"typeKey": "running"},
        }],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_activity",
        return_value={
            "activityId": 1,
            "startTimeLocal": "2026-07-10T08:00:00",
            "activityType": {"typeKey": "running"},
            "metadataDTO": {"associatedWorkoutId": 10},
        },
    )
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_workout",
        return_value={
            "workoutId": 10,
            "workoutName": "Pace",
            "sportType": {"sportTypeKey": "running"},
            "workoutSegments": [{
                "sportType": {"sportTypeKey": "running"},
                "workoutSteps": [{
                    "stepOrder": 1,
                    "stepType": {"stepTypeKey": "interval"},
                    "durationType": "time",
                    "durationValue": 600,
                    "targetType": {"workoutTargetTypeKey": "speed.zone"},
                    "targetValueOne": 2.5,
                    "targetValueTwo": 3.5,
                }],
            }],
        },
    )
    mocker.patch("garmin_cli.mcp_tools.coaching.get_activity_splits", return_value={})
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_activity_hr_in_timezones",
        return_value=[],
    )
    stream = mocker.patch("garmin_cli.mcp_tools.coaching.get_activity_details")
    server = create_mcp_server(_config())

    result = _call(
        server,
        "training_plan_reconcile",
        {
            "start_date": "2026-07-01",
            "end_date": "2026-07-14",
            "detail": "targets",
        },
    )

    stream.assert_not_called()
    comparison = result["entries"][0]["target_comparison"]
    assert comparison["targets"][0]["reason"] == "stream_request_limit_reached"
    assert result["provenance"]["stream_requests"] == 0
    assert result["provenance"]["stream_truncated"] is True
