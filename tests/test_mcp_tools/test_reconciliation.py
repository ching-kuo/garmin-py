"""MCP boundary tests for bounded reconciliation."""
from __future__ import annotations

from typing import Any

import pytest

from tests.helpers import require_mcp

require_mcp()

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


def _power_zone_reconcile(
    mocker: Any, rides: list[tuple[str, str, str, int]], power_zones: Any
) -> tuple[dict, Any, Any]:
    """Run targets-mode reconcile over (date, activity typeKey, workout sport, zone) rides."""
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_calendar_range",
        return_value=[
            {"date": day, "workoutId": 10 + index, "workoutTypeKey": sport}
            for index, (day, _type, sport, _zone) in enumerate(rides)
        ],
    )
    activities = {
        1 + index: {
            "activityId": 1 + index,
            "startTimeLocal": f"{day}T08:00:00",
            "activityType": {"typeKey": type_key},
            "metadataDTO": {"associatedWorkoutId": 10 + index},
        }
        for index, (day, type_key, _sport, _zone) in enumerate(rides)
    }
    workouts = {
        10 + index: {
            "workoutId": 10 + index,
            "workoutName": "Power",
            "sportType": {"sportTypeKey": sport},
            "workoutSegments": [{
                "segmentOrder": 1,
                "sportType": {"sportTypeKey": sport},
                "workoutSteps": [{
                    "stepOrder": 1,
                    "stepType": {"stepTypeKey": "interval"},
                    "endCondition": {"conditionTypeKey": "time"},
                    "endConditionValue": 600,
                    "targetType": {"workoutTargetTypeKey": "power.zone"},
                    "zoneNumber": zone,
                }],
            }],
        }
        for index, (_day, _type, sport, zone) in enumerate(rides)
    }
    mocker.patch("garmin_cli.mcp_tools.coaching.list_activities", return_value=list(activities.values()))
    mocker.patch("garmin_cli.mcp_tools.coaching.get_activity", side_effect=activities.__getitem__)
    mocker.patch("garmin_cli.mcp_tools.coaching.get_workout", side_effect=workouts.__getitem__)
    mocker.patch("garmin_cli.mcp_tools.coaching.get_activity_splits", return_value={})
    mocker.patch("garmin_cli.mcp_tools.coaching.get_activity_hr_in_timezones", return_value=[])
    zones = mocker.patch("garmin_cli.mcp_tools.coaching.get_power_zones", side_effect=power_zones)
    stream = mocker.patch(
        "garmin_cli.mcp_tools.coaching.get_activity_details",
        return_value={
            "metricDescriptors": [{"key": "directPower", "metricsIndex": 0, "unit": {"key": "watt"}}],
            "activityDetailMetrics": [{"metrics": [220.0]}, {"metrics": [246.0]}, {"metrics": [400.0]}],
        },
    )
    result = _call(
        create_mcp_server(_config()),
        "training_plan_reconcile",
        {"start_date": "2026-07-01", "end_date": "2026-07-14", "detail": "targets"},
    )
    return result, zones, stream


def _targets(result: dict) -> list[dict]:
    entries = sorted(result["entries"], key=lambda entry: entry["actual"]["date"])
    return [entry["target_comparison"]["targets"][0] for entry in entries]


def test_targets_mode_resolves_power_zone_targets_from_the_athlete_zone_table(
    mocker: Any, sample_zone_tables_raw: dict
) -> None:
    by_sport = {table["sport"]: table for table in sample_zone_tables_raw["power"]}
    result, zones, _stream = _power_zone_reconcile(
        mocker,
        [("2026-07-10", "road_biking", "cycling", 4), ("2026-07-11", "running", "running", 5)],
        by_sport.__getitem__,
    )

    assert sorted(call.args[0] for call in zones.call_args_list) == ["CYCLING", "RUNNING"]
    ride, run = _targets(result)
    assert ride["resolved_band"] == {"min": 211.0, "max": 246.0}
    # 246 W is zone 5's floor, so only the 220 W sample is in zone 4.
    assert ride["time_in_band_pct"] == 33.3
    assert ride["quality"] == "sampled_stream"
    assert run["resolved_band"] == {"min": 372.0, "max": None}
    assert run["time_in_band_pct"] == 33.3
    assert result["provenance"]["power_zone_requests"] == 2


def test_power_zone_fetch_failure_leaves_the_target_insufficient(mocker: Any) -> None:
    from garmin_cli.exceptions import GarminCliError

    error = GarminCliError(error="Garmin server error.", error_code="SERVER_ERROR")
    result, _zones, stream = _power_zone_reconcile(mocker, [("2026-07-10", "road_biking", "cycling", 4)], error)

    (target,) = _targets(result)
    assert target["reason"] == "missing_power_zone_boundaries"
    # An unresolved zone needs no stream.
    stream.assert_not_called()
    assert result["provenance"]["power_zone_requests"] == 1


@pytest.mark.parametrize("error_code", ["AUTH_FAILED", "RATE_LIMITED"])
def test_power_zone_auth_and_rate_limit_errors_fail_the_call(mocker: Any, error_code: str) -> None:
    from mcp.server.mcpserver.exceptions import ToolError

    from garmin_cli.exceptions import GarminCliError

    with pytest.raises(ToolError, match=error_code):
        _power_zone_reconcile(
            mocker,
            [("2026-07-10", "road_biking", "cycling", 4)],
            GarminCliError(error="Stopped.", error_code=error_code),
        )


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
