"""Activity MCP tool tests (moved from test_mcp_server.py; assertions unchanged)."""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


class TestActivityTools:

    def test_activity_list(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.activities.list_activities", return_value=[{"activityId": 1, "startTimeLocal": "2026-01-01", "activityName": "Run", "activityType": {"typeKey": "running"}, "distance": 5000, "duration": 1800, "averageHR": 150}])
        server = create_mcp_server(_config())
        result = _call(server, "activity_list", {"limit": 10})
        assert result["count"] == 1
        assert result["rows"][0]["id"] == 1

    def test_activity_list_with_filters(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mock_list = mocker.patch("garmin_cli.mcp_tools.activities.list_activities", return_value=[])
        server = create_mcp_server(_config())
        _call(server, "activity_list", {"limit": 5, "start": 10, "activity_type": "running", "search": "morning"})
        mock_list.assert_called_once_with(5, 10, "running", "morning", None, None)

    def test_activity_list_with_date_range(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mock_list = mocker.patch("garmin_cli.mcp_tools.activities.list_activities", return_value=[])
        server = create_mcp_server(_config())
        _call(server, "activity_list", {"start_date": "2026-03-01", "end_date": "2026-03-10"})
        mock_list.assert_called_once_with(20, 0, None, None, date(2026, 3, 1), date(2026, 3, 10))

    def test_activity_list_start_date_only_raises(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        server = create_mcp_server(_config())
        with pytest.raises(Exception, match="start_date and end_date must be provided together"):
            _call(server, "activity_list", {"start_date": "2026-03-15"})

    def test_activity_list_end_date_only_raises(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        server = create_mcp_server(_config())
        with pytest.raises(Exception, match="start_date and end_date must be provided together"):
            _call(server, "activity_list", {"end_date": "2026-03-10"})

    def test_activity_get(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.activities.get_activity", return_value={"activityId": 123, "startTimeLocal": "2026-01-01", "activityName": "Run", "activityType": {"typeKey": "running"}, "distance": 10000, "duration": 3600, "averageHR": 155})
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 123})
        assert result["count"] == 1
        assert result["rows"][0]["id"] == 123

    def test_activity_get_detail_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={
                "activityId": 123,
                "startTimeLocal": "2026-01-01",
                "activityName": "Run",
                "activityType": {"typeKey": "running"},
                "distance": 10000,
                "duration": 3600,
                "averageHR": 155,
                "maxHR": 178,
                "calories": 650,
                "elevationGain": 120.0,
                "elevationLoss": 100.0,
                "averageSpeed": 2.778,
                "maxSpeed": 4.0,
                "averageRunningCadenceInStepsPerMinute": 180.0,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 123, "detail": True})
        assert result["count"] == 1
        row = result["rows"][0]
        assert "max_hr" in row
        assert "calories" in row
        assert "elevation_gain_m" in row
        assert "avg_speed_kmh" in row
        assert "avg_cadence_spm" in row

    def test_activity_get_default_compact(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={
                "activityId": 123,
                "startTimeLocal": "2026-01-01",
                "activityName": "Run",
                "activityType": {"typeKey": "running"},
                "distance": 10000,
                "duration": 3600,
                "averageHR": 155,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 123})
        assert result["count"] == 1
        row = result["rows"][0]
        assert "id" in row
        assert "max_hr" not in row

    def test_activity_get_detail_false_compact(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={
                "activityId": 123,
                "startTimeLocal": "2026-01-01",
                "activityName": "Run",
                "activityType": {"typeKey": "running"},
                "distance": 10000,
                "duration": 3600,
                "averageHR": 155,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 123, "detail": False})
        assert result["count"] == 1
        row = result["rows"][0]
        assert "id" in row
        assert "max_hr" not in row

    def test_activity_get_detail_returns_running_dynamics(self, mocker: Any) -> None:
        """U5: MCP activity_get(detail=True) on a run returns running-dynamics keys."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={
                "activityId": 200,
                "activityType": {"typeKey": "running"},
                "averageRunningCadenceInStepsPerMinute": 180.0,
                "avgGroundContactTime": 240,
                "avgVerticalOscillation": 8.4,
                "avgVerticalRatio": 6.5,
                "avgStrideLength": 132.0,
                "aerobicTrainingEffect": 3.2,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 200, "detail": True})
        row = result["rows"][0]
        assert row["avg_cadence_spm"] == 180.0
        assert row["avg_ground_contact_time"] == 240
        assert row["avg_vertical_oscillation"] == 8.4
        assert row["aerobic_training_effect"] == 3.2

    def test_activity_get_detail_returns_union_keys_with_nulls(self, mocker: Any) -> None:
        """U5: MCP activity_get(detail=True) emits the union schema."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={
                "activityId": 201,
                "activityType": {"typeKey": "running"},
                "averageRunningCadenceInStepsPerMinute": 175.0,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 201, "detail": True})
        row = result["rows"][0]
        # cycling/swim union keys present but null
        for key in ("avg_power_w", "norm_power_w", "tss", "swolf", "total_strokes"):
            assert key in row
            assert row[key] is None

    def test_activity_get_detail_cycling_returns_power_suite(self, mocker: Any) -> None:
        """U5: MCP activity_get(detail=True) on a ride returns cycling power keys."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={
                "activityId": 300,
                "activityType": {"typeKey": "cycling"},
                "averagePower": 220.0,
                "maxPower": 600.0,
                "normPower": 235.0,
                "trainingStressScore": 95.0,
                "intensityFactor": 0.88,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 300, "detail": True})
        row = result["rows"][0]
        assert row["avg_power_w"] == 220.0
        assert row["norm_power_w"] == 235.0
        assert row["tss"] == 95.0
        assert row["intensity_factor"] == 0.88

    def test_activity_get_detail_lap_swim_returns_swim_metrics(self, mocker: Any) -> None:
        """U5: MCP activity_get(detail=True) on a swim returns swim aggregates."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={
                "activityId": 400,
                "activityType": {"typeKey": "lap_swimming"},
                "avgSwolf": 38,
                "strokes": 720,
                "averageStrokeRate": 28.5,
                "avgStrokeDistance": 1.85,
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 400, "detail": True})
        row = result["rows"][0]
        assert row["swolf"] == 38
        assert row["total_strokes"] == 720
        assert row["avg_stroke_rate"] == 28.5
        assert row["distance_per_stroke"] == 1.85

    def test_activity_weather(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity_weather",
            return_value={
                "temp": 20,
                "apparentTemp": 19,
                "dewPoint": 10,
                "relativeHumidity": 60,
                "windSpeed": 5,
                "windGust": 8,
                "windDirection": 180,
                "windDirectionCompassPoint": "s",
                "weatherTypeDTO": {"desc": "Cloudy"},
            },
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_weather", {"activity_id": 123})
        assert result["count"] == 1
        row = result["rows"][0]
        assert row["temperature"] == 20
        assert row["humidity"] == 60
        assert row["wind_direction"] == 180
        assert row["condition"] == "Cloudy"

    def test_activity_get_detail_emits_unavailable_manifest(self, mocker: Any) -> None:
        """U11: detail=True attaches unavailable[] to MCP envelope when non-empty."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "running"}},
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 1, "detail": True})
        assert "unavailable" in result
        reasons = {e["field"]: e["reason"] for e in result["unavailable"]}
        assert reasons.get("avg_power_w") == "not_applicable_to_sport"
        assert reasons.get("swolf") == "not_applicable_to_sport"

    def test_activity_get_detail_false_omits_manifest(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "running"}},
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 1, "detail": False})
        assert "unavailable" not in result

    def test_activity_get_multisport_unions_child_manifests(self, mocker: Any) -> None:
        """U11: multisport parent envelope unions children with leg_index."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={
                "activityId": 100,
                "activityType": {"typeKey": "multi_sport"},
                "isMultiSportParent": True,
                "childIds": [101, 102, 103],
            },
        )
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_multisport_children",
            return_value=[
                {"activityId": 101, "activityType": {"typeKey": "open_water_swimming"}, "averageHR": 145},
                {"activityId": 102, "activityType": {"typeKey": "cycling"}, "averagePower": 200},
                {"activityId": 103, "activityType": {"typeKey": "running"}, "averageRunningCadenceInStepsPerMinute": 175},
            ],
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 100, "detail": True})
        assert "unavailable" in result
        leg_indices = {e["leg_index"] for e in result["unavailable"]}
        assert leg_indices == {0, 1, 2}

    def test_activity_get_summary_no_manifest_for_simple_activity(self, mocker: Any) -> None:
        """detail=False never carries manifest, even for unknown sports."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "weightlifting"}},
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_get", {"activity_id": 1})
        assert "unavailable" not in result

    def test_activity_laps_run_uses_raw_splits(self, mocker: Any) -> None:
        """U8: running activity routes to get_activity_splits (raw URL)."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={"activityId": 123, "activityType": {"typeKey": "running"}},
        )
        splits = mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity_splits",
            return_value={"lapDTOs": [
                {"duration": 480, "distance": 1000, "averageHR": 162, "avgGroundContactTime": 235},
                {"duration": 470, "distance": 1000, "averageHR": 168, "avgGroundContactTime": 230},
            ]},
        )
        typed = mocker.patch("garmin_cli.mcp_tools.activities.get_activity_typed_splits")
        server = create_mcp_server(_config())
        result = _call(server, "activity_laps", {"activity_id": 123})
        assert result["count"] == 2
        assert result["rows"][0]["avg_ground_contact_time"] == 235
        splits.assert_called_once_with(123)
        typed.assert_not_called()

    def test_activity_laps_pool_swim_uses_typed_splits(self, mocker: Any) -> None:
        """U8: lap_swimming routes to get_activity_typed_splits (typed method)."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={"activityId": 456, "activityType": {"typeKey": "lap_swimming"}},
        )
        splits = mocker.patch("garmin_cli.mcp_tools.activities.get_activity_splits")
        typed = mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity_typed_splits",
            return_value={"lengthDTOs": [
                {"duration": 25.0, "distance": 25.0, "swolf": 38, "swimStroke": "FREESTYLE", "strokes": 14},
                {"duration": 26.0, "distance": 25.0, "swolf": 39, "swimStroke": "FREESTYLE", "strokes": 15},
            ]},
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_laps", {"activity_id": 456})
        assert result["count"] == 2
        assert result["rows"][0]["swolf"] == 38
        assert result["rows"][0]["stroke_type"] == "FREESTYLE"
        typed.assert_called_once_with(456)
        splits.assert_not_called()

    def test_activity_laps_open_water_swim_uses_raw_splits(self, mocker: Any) -> None:
        """U8: open_water_swimming routes to splits (lapDTOs), not typed_splits."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={"activityId": 789, "activityType": {"typeKey": "open_water_swimming"}},
        )
        splits = mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity_splits",
            return_value={"lapDTOs": [{"duration": 600, "distance": 1000, "averageHR": 140}]},
        )
        typed = mocker.patch("garmin_cli.mcp_tools.activities.get_activity_typed_splits")
        server = create_mcp_server(_config())
        result = _call(server, "activity_laps", {"activity_id": 789})
        assert result["count"] == 1
        splits.assert_called_once()
        typed.assert_not_called()

    def test_activity_laps_invalid_id_raises_tool_error(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_laps", {"activity_id": 0})

    def test_activity_laps_multisport_fan_out_with_leg_index(self, mocker: Any) -> None:
        """Multisport parent laps fetches each child and stamps leg_index."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity",
            return_value={
                "activityId": 100,
                "activityType": {"typeKey": "multi_sport"},
                "isMultiSportParent": True,
                "childIds": [101, 102, 103],
            },
        )
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_multisport_children",
            return_value=[
                {"activityId": 101, "activityType": {"typeKey": "open_water_swimming"}},
                {"activityId": 102, "activityType": {"typeKey": "cycling"}},
                {"activityId": 103, "activityType": {"typeKey": "running"}},
            ],
        )
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity_splits",
            side_effect=[
                {"lapDTOs": [{"duration": 600, "distance": 1000, "averageHR": 140}]},
                {"lapDTOs": [{"duration": 1200, "distance": 8000, "averagePower": 220}]},
                {"lapDTOs": [{"duration": 900, "distance": 3000, "avgGroundContactTime": 235}]},
            ],
        )
        mocker.patch("garmin_cli.mcp_tools.activities.get_activity_typed_splits")
        server = create_mcp_server(_config())
        result = _call(server, "activity_laps", {"activity_id": 100})
        assert result["count"] == 3
        leg_indices = {row["leg_index"] for row in result["rows"]}
        assert leg_indices == {0, 1, 2}

    def test_activity_hr_zones_returns_envelope(self, mocker: Any) -> None:
        """U10: activity_hr_zones returns one row per zone."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity_hr_in_timezones",
            return_value=[
                {"zoneNumber": z, "zoneLowBoundary": 100 + z, "zoneHighBoundary": 110 + z, "secsInZone": 60 * z}
                for z in range(1, 6)
            ],
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_hr_zones", {"activity_id": 1})
        assert result["count"] == 5
        assert result["rows"][0]["zone"] == 1
        assert result["rows"][4]["zone"] == 5

    def test_activity_hr_zones_empty_returns_zero_count(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.activities.get_activity_hr_in_timezones", return_value=[])
        server = create_mcp_server(_config())
        result = _call(server, "activity_hr_zones", {"activity_id": 1})
        assert result["count"] == 0
        assert result["rows"] == []

    def test_activity_hr_zones_invalid_id_raises_tool_error(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_hr_zones", {"activity_id": -1})

    def test_activity_metrics_describe_returns_descriptors(self, mocker: Any) -> None:
        """U12: activity_metrics_describe returns one row per metric descriptor."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.activities.get_activity_details",
            return_value={"metricDescriptors": [
                {"key": "directHeartRate", "unit": {"key": "bpm"}, "metricsIndex": 0},
                {"key": "directPower", "unit": {"key": "W"}, "metricsIndex": 1},
            ]},
        )
        server = create_mcp_server(_config())
        result = _call(server, "activity_metrics_describe", {"activity_id": 1})
        assert result["count"] == 2
        keys = {row["key"] for row in result["rows"]}
        assert keys == {"directHeartRate", "directPower"}

    def test_activity_metrics_describe_empty(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.activities.get_activity_details", return_value={})
        server = create_mcp_server(_config())
        result = _call(server, "activity_metrics_describe", {"activity_id": 1})
        assert result["count"] == 0
        assert result["rows"] == []

    def test_activity_metrics_describe_invalid_id(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_metrics_describe", {"activity_id": 0})
