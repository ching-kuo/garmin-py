"""Performance trend surfaces: FTP history, acclimation, cycling ability,
power curve, fastest splits (endpoints, serializers, CLI, MCP).

Wire shapes below mirror live responses observed on 2026-11-09 (values are
synthetic).
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from click.testing import CliRunner

pytest.importorskip("mcp")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli.cli import cli  # noqa: E402
from garmin_cli.endpoints import metrics as metrics_endpoints  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from garmin_cli.serializers.trends import (  # noqa: E402
    serialize_acclimation,
    serialize_cycling_ability,
    serialize_fastest_splits,
    serialize_ftp_history,
    serialize_power_curve,
)
from tests.test_mcp_tools.support import _call, _config  # noqa: E402

START, END = date(2026, 10, 1), date(2026, 10, 14)

FTP_RAW = [{"from": "2026-10-02", "until": "2026-10-02", "series": "cycling", "value": 250.0, "updatedDate": "2026-10-02"}]
ACCLIMATION_RAW = [{
    "calendarDate": "2026-10-02",
    "heatAcclimationPercentage": 21,
    "heatTrend": "DEACCLIMATIZING",
    "altitudeAcclimation": 0,
    "altitudeTrend": None,
    "currentAltitude": 15,
}]
CYCLING_ABILITY_RAW = {
    "startDate": "2026-10-01",
    "endDate": "2026-10-14",
    "cyclingAbilitiesMap": {
        "2026-10-03": {"calendarDate": "2026-10-03", "aerobicEndurance": 80, "aerobicCapacity": 70,
                       "anaerobicCapacity": 50, "profileType": "TIME_TRIALIST",
                       "aerobicEnduranceFeedback": "A", "aerobicCapacityFeedback": "B",
                       "anaerobicCapacityFeedback": "C"},
        "2026-10-02": {"aerobicEndurance": 79},  # date only in the map key
    },
}
POWER_CURVE_RAW = {"startDate": "2026-10-01", "endDate": "2026-10-14", "entries": [
    {"duration": 1, "power": 600, "activityId": 11, "activityDate": "2026-10-04"},
    {"duration": 1200, "power": 260, "activityId": 12, "activityDate": "2026-10-05"},
]}
FASTEST_RAW = [{"distance": 1000, "activityId": 21, "activityDate": "2026-10-06", "time": 259.65899658203125}]


class TestEndpoints:
    @pytest.mark.parametrize(
        ("call", "path", "params"),
        [
            (
                lambda: metrics_endpoints.get_ftp_history(START, END, "cycling"),
                "/biometric-service/stats/functionalThresholdPower/range/2026-10-01/2026-10-14",
                {"sport": "CYCLING", "aggregation": "daily", "aggregationStrategy": "LATEST"},
            ),
            (
                lambda: metrics_endpoints.get_acclimation_range(START, END),
                "/metrics-service/metrics/heataltitudeacclimation/daily/2026-10-01/2026-10-14",
                None,
            ),
            (
                lambda: metrics_endpoints.get_cycling_ability_range(START, END),
                "/metrics-service/metrics/cycling-ability",
                {"startDate": "2026-10-01", "endDate": "2026-10-14", "aggregation": "DAILY"},
            ),
            (
                lambda: metrics_endpoints.get_power_curve(START, END, "rowing"),
                "/fitnessstats-service/powerCurve",
                {"startDate": "2026-10-01", "endDate": "2026-10-14", "sport": "rowing"},
            ),
            (
                lambda: metrics_endpoints.get_fastest_splits(START, END, "running", 3),
                "/activitylist-service/activities/fastest-splits",
                {"startDate": "2026-10-01", "endDate": "2026-10-14", "activityType": "running", "numberOfBests": 3},
            ),
        ],
    )
    def test_request_shape(self, mocker: Any, call: Any, path: str, params: Any) -> None:
        request = mocker.patch("garmin_cli.endpoints.metrics._request", return_value=[])
        call()
        request.assert_called_once_with(path, **({} if params is None else {"params": params}))

    def test_none_payload_coalesces(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.endpoints.metrics._request", return_value=None)
        assert metrics_endpoints.get_acclimation_range(START, END) == []
        assert metrics_endpoints.get_cycling_ability_range(START, END) == {}


class TestSerializers:
    def test_ftp_history(self) -> None:
        assert serialize_ftp_history(FTP_RAW) == [{"date": "2026-10-02", "sport": "cycling", "ftp_watts": 250.0}]

    def test_acclimation(self) -> None:
        assert serialize_acclimation(ACCLIMATION_RAW) == [{
            "date": "2026-10-02",
            "heat_acclimation_pct": 21,
            "heat_trend": "DEACCLIMATIZING",
            "altitude_acclimation": 0,
            "altitude_trend": None,
            "current_altitude": 15,
        }]

    def test_cycling_ability_flattens_date_map_in_date_order(self) -> None:
        rows = serialize_cycling_ability(CYCLING_ABILITY_RAW)
        assert [row["date"] for row in rows] == ["2026-10-02", "2026-10-03"]
        assert rows[1] == {
            "date": "2026-10-03",
            "aerobic_endurance": 80,
            "aerobic_capacity": 70,
            "anaerobic_capacity": 50,
            "profile_type": "TIME_TRIALIST",
            "aerobic_endurance_feedback": "A",
            "aerobic_capacity_feedback": "B",
            "anaerobic_capacity_feedback": "C",
        }

    def test_cycling_ability_tolerates_missing_map(self) -> None:
        assert serialize_cycling_ability({}) == []
        assert serialize_cycling_ability(None) == []

    def test_power_curve(self) -> None:
        assert serialize_power_curve(POWER_CURVE_RAW)[1] == {
            "duration_s": 1200, "power_w": 260, "activity_id": 12, "activity_date": "2026-10-05",
        }

    def test_fastest_splits_rounds_time(self) -> None:
        assert serialize_fastest_splits(FASTEST_RAW) == [
            {"distance_m": 1000, "time_s": 259.7, "activity_id": 21, "activity_date": "2026-10-06"},
        ]


class TestCli:
    @pytest.mark.parametrize(
        ("args", "getter", "raw", "first_key"),
        [
            (["ftp-history", "--sport", "running"], "get_ftp_history", FTP_RAW, "ftp_watts"),
            (["acclimation"], "get_acclimation_range", ACCLIMATION_RAW, "heat_acclimation_pct"),
            (["cycling-ability"], "get_cycling_ability_range", CYCLING_ABILITY_RAW, "aerobic_endurance"),
            (["power-curve"], "get_power_curve", POWER_CURVE_RAW, "power_w"),
            (["fastest-splits", "--bests", "2"], "get_fastest_splits", FASTEST_RAW, "time_s"),
        ],
    )
    def test_command_renders_rows(
        self, mocker: Any, args: list[str], getter: str, raw: Any, first_key: str
    ) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        fetch = mocker.patch(f"garmin_cli.commands.performance.{getter}", return_value=raw)

        result = CliRunner(mix_stderr=False).invoke(
            cli, ["--json", "performance", *args, "--from", "2026-10-01", "--to", "2026-10-14"]
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert first_key in payload["data"][0]
        assert fetch.call_args.args[:2] == (START, END)

    def test_options_reach_the_endpoint(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.ensure_authenticated")
        fetch = mocker.patch("garmin_cli.commands.performance.get_fastest_splits", return_value=[])
        CliRunner(mix_stderr=False).invoke(
            cli, ["performance", "fastest-splits", "--sport", "cycling", "--bests", "3", "--days", "7"]
        )
        assert fetch.call_args.args[2:] == ("cycling", 3)

    @pytest.mark.parametrize(
        "args",
        [
            ["power-curve", "--sport", "running"],
            ["ftp-history", "--sport", "swimming"],
            ["fastest-splits", "--bests", "0"],
            ["fastest-splits", "--bests", "11"],
        ],
    )
    def test_rejects_unsupported_options(self, args: list[str]) -> None:
        result = CliRunner(mix_stderr=False).invoke(cli, ["performance", *args, "--days", "7"])
        assert result.exit_code != 0


class TestMcp:
    @pytest.mark.parametrize(
        ("tool", "args", "getter", "raw", "first_key"),
        [
            ("performance_ftp_history", {"sport": "running"}, "get_ftp_history", FTP_RAW, "ftp_watts"),
            ("performance_acclimation", {}, "get_acclimation_range", ACCLIMATION_RAW, "heat_trend"),
            ("performance_cycling_ability", {}, "get_cycling_ability_range", CYCLING_ABILITY_RAW, "profile_type"),
            ("performance_power_curve", {"sport": "rowing"}, "get_power_curve", POWER_CURVE_RAW, "duration_s"),
            ("performance_fastest_splits", {"bests_per_distance": 2}, "get_fastest_splits", FASTEST_RAW, "distance_m"),
        ],
    )
    def test_tool_returns_rows(
        self, mocker: Any, tool: str, args: dict[str, Any], getter: str, raw: Any, first_key: str
    ) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        fetch = mocker.patch(f"garmin_cli.mcp_tools.performance.{getter}", return_value=raw)

        result = _call(
            create_mcp_server(_config()),
            tool,
            {"start_date": "2026-10-01", "end_date": "2026-10-14", **args},
        )

        assert result["count"] >= 1
        assert first_key in result["rows"][0]
        assert fetch.call_args.args[:2] == (START, END)
        for value in args.values():
            assert value in fetch.call_args.args

    @pytest.mark.parametrize(
        ("tool", "args"),
        [
            ("performance_power_curve", {"sport": "running"}),
            ("performance_ftp_history", {"sport": "swimming"}),
            ("performance_fastest_splits", {"bests_per_distance": 0}),
            ("performance_fastest_splits", {"bests_per_distance": 11}),
            ("performance_acclimation", {"end_date": "2027-01-01"}),
        ],
    )
    def test_tool_rejects_invalid_input(self, tool: str, args: dict[str, Any]) -> None:
        with pytest.raises(ToolError):
            _call(
                create_mcp_server(_config()),
                tool,
                {"start_date": "2026-10-01", "end_date": "2026-10-14", **args},
            )
