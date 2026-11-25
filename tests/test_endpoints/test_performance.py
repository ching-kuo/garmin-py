"""Tests for garmin_cli.endpoints.performance — threshold and VO2max functions."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.performance import (
    get_all_thresholds,
    get_ftp,
    get_latest_vo2max,
    get_lactate_threshold,
    get_personal_records,
    get_vo2max,
    get_zone_tables,
)
from garmin_cli.exceptions import GarminCliError
from tests.helpers import make_http_error as _http_error


# ---------------------------------------------------------------------------
# get_personal_records
# ---------------------------------------------------------------------------

class TestGetPersonalRecords:

    def test_uses_typed_upstream_helper(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_personal_records.return_value = [{"typeId": 1, "value": 219.76}]
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        result = get_personal_records()
        assert result == [{"typeId": 1, "value": 219.76}]
        mock_garth.get_personal_records.assert_called_once_with()

    def test_none_response_coalesces_to_empty_list(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_personal_records.return_value = None
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        assert get_personal_records() == []

    def test_http_404_raises_not_found_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_personal_records.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_personal_records()
        assert exc_info.value.error_code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# get_zone_tables
# ---------------------------------------------------------------------------

class TestGetZoneTables:

    @pytest.fixture(autouse=True)
    def _no_fan_out_delay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "0")

    def test_reads_hr_v2_and_per_sport_power_zones(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        responses = {
            "/biometric-service/heartRateZones/v2": [{"sport": "DEFAULT", "zone1Floor": 118}],
            "/biometric-service/powerZones/sport/CYCLING": {"sport": "CYCLING", "zone1Floor": 0.0},
        }

        def connectapi(path: str, params: Any = None) -> Any:
            if path.endswith("RUNNING"):
                raise _http_error(404)
            return responses[path]

        mock_garth.connectapi.side_effect = connectapi
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        result = get_zone_tables()

        # A sport without power zones (404) is left out rather than failing.
        assert result == {
            "heart_rate": [{"sport": "DEFAULT", "zone1Floor": 118}],
            "power": [{"sport": "CYCLING", "zone1Floor": 0.0}],
        }
        hr_call = next(c for c in mock_garth.connectapi.call_args_list if "heartRateZones" in c.args[0])
        assert hr_call.kwargs["params"] == {"generateDefaults": "false"}

    def test_rejected_power_table_is_missing_and_hr_rows_remain(self, mocker: Any) -> None:
        def connectapi(path: str, params: Any = None) -> Any:
            if path.endswith("RUNNING"):
                raise _http_error(400)
            return {"sport": "CYCLING"} if "powerZones" in path else [{"sport": "DEFAULT"}]

        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = connectapi
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        assert get_zone_tables() == {"heart_rate": [{"sport": "DEFAULT"}], "power": [{"sport": "CYCLING"}]}

    def test_rate_limited_power_read_propagates(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.endpoints.performance.get_heart_rate_zones", return_value=[])
        mocker.patch(
            "garmin_cli.endpoints.performance.get_power_zones",
            side_effect=GarminCliError(error="Slow down.", error_code="RATE_LIMITED"),
        )

        with pytest.raises(GarminCliError) as exc_info:
            get_zone_tables()
        assert exc_info.value.error_code == "RATE_LIMITED"

    def test_power_errors_other_than_not_found_propagate(self, mocker: Any) -> None:
        def connectapi(path: str, params: Any = None) -> Any:
            if "powerZones" in path:
                raise _http_error(403)
            return []

        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = connectapi
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_zone_tables()
        assert exc_info.value.error_code != "NOT_FOUND"


# ---------------------------------------------------------------------------
# get_lactate_threshold
# ---------------------------------------------------------------------------

class TestGetLactateThreshold:

    def test_uses_verified_latest_lactate_threshold_endpoint(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        get_lactate_threshold()
        call_str = str(mock_garth.connectapi.call_args)
        assert "/biometric-service/biometric/latestLactateThreshold" in call_str

    def test_http_404_raises_not_found_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_lactate_threshold()
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_http_500_raises_server_error_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [_http_error(500)] * 4
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            get_lactate_threshold()
        assert exc_info.value.error_code == "SERVER_ERROR"


# ---------------------------------------------------------------------------
# get_ftp
# ---------------------------------------------------------------------------

class TestGetFtp:

    def test_http_404_raises_not_found_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_ftp(sport="cycling")
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_uses_verified_power_to_weight_endpoint(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        get_ftp(sport="cycling")
        call_str = str(mock_garth.connectapi.call_args)
        assert "/biometric-service/biometric/powerToWeight/latest/" in call_str
        assert "Cycling" in call_str


# ---------------------------------------------------------------------------
# get_vo2max
# ---------------------------------------------------------------------------

class TestGetVo2max:

    def test_http_404_raises_not_found_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_vo2max(date(2026, 3, 11))
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_http_500_raises_server_error_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [_http_error(500)] * 4
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            get_vo2max(date(2026, 3, 11))
        assert exc_info.value.error_code == "SERVER_ERROR"

    def test_uses_verified_maxmet_daily_endpoint(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        get_vo2max(date(2026, 3, 11))
        call_str = str(mock_garth.connectapi.call_args)
        assert "/metrics-service/metrics/maxmet/daily/2026-03-11/2026-03-11" in call_str

    def test_latest_queries_recent_range(self, mocker: Any) -> None:
        mock_request = mocker.patch(
            "garmin_cli.endpoints.performance._request",
            return_value=[],
        )

        get_latest_vo2max()

        call_url = mock_request.call_args[0][0]
        assert "/metrics-service/metrics/maxmet/daily/" in call_url


# ---------------------------------------------------------------------------
# get_all_thresholds
# ---------------------------------------------------------------------------

class TestGetAllThresholds:

    def test_returns_dict(self, mocker: Any, sample_all_thresholds_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_all_thresholds_raw
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        result = get_all_thresholds()
        assert isinstance(result, dict)

    def test_http_500_raises_server_error_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [_http_error(500)] * 8
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            get_all_thresholds()
        assert exc_info.value.error_code == "SERVER_ERROR"

    def test_empty_thresholds_returns_empty_dict(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        result = get_all_thresholds()
        # Returns dict (possibly empty if no threshold data available)
        assert isinstance(result, dict)

    def test_missing_optional_ftp_does_not_abort_aggregation(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.performance.get_lactate_threshold",
            return_value={
                "sport": "running",
                "lactateThresholdHeartRate": 172,
                "lactateThresholdPace": 255,
            },
        )
        mocker.patch(
            "garmin_cli.endpoints.performance.get_ftp",
            side_effect=[
                GarminCliError(error="missing", error_code="NOT_FOUND"),
                {"sport": "running", "functionalThresholdPower": 315, "weight": 70.5},
            ],
        )

        result = get_all_thresholds()

        assert result["thresholds"] == [
            {
                "sport": "running",
                "lactateThresholdHeartRate": 172,
                "lactateThresholdPace": "4:15",
                "functionalThresholdPower": 315,
                "weight": 70.5,
            }
        ]

    def test_list_power_to_weight_payload_is_merged(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.performance.get_lactate_threshold",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.endpoints.performance.get_ftp",
            side_effect=[
                [{"sport": "cycling", "functionalThresholdPower": 260, "weight": 68.0}],
                [{"sport": "running", "functionalThresholdPower": 310, "weight": 68.0}],
            ],
        )

        result = get_all_thresholds()

        assert result["thresholds"] == [
            {
                "sport": "cycling",
                "lactateThresholdHeartRate": None,
                "lactateThresholdPace": None,
                "functionalThresholdPower": 260,
                "weight": 68.0,
            },
            {
                "sport": "running",
                "lactateThresholdHeartRate": None,
                "lactateThresholdPace": None,
                "functionalThresholdPower": 310,
                "weight": 68.0,
            },
        ]

    def test_running_thresholds_are_merged_into_single_row(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.performance.get_lactate_threshold",
            return_value={
                "sport": "running",
                "lactateThresholdHeartRate": 171,
                "lactateThresholdPace": 250,
                "weight": 68.0,
            },
        )
        mocker.patch(
            "garmin_cli.endpoints.performance.get_ftp",
            side_effect=[
                {"sport": "cycling", "functionalThresholdPower": 260, "weight": 68.0},
                {"sport": "running", "functionalThresholdPower": 310, "weight": 68.0},
            ],
        )

        result = get_all_thresholds()

        assert result["thresholds"] == [
            {
                "sport": "running",
                "lactateThresholdHeartRate": 171,
                "lactateThresholdPace": "4:10",
                "functionalThresholdPower": 310,
                "weight": 68.0,
            },
            {
                "sport": "cycling",
                "lactateThresholdHeartRate": None,
                "lactateThresholdPace": None,
                "functionalThresholdPower": 260,
                "weight": 68.0,
            },
        ]

    def test_speed_based_lactate_threshold_is_normalized_to_pace(
        self, mocker: Any, sample_lactate_threshold_raw: Any
    ) -> None:
        mocker.patch(
            "garmin_cli.endpoints.performance.get_lactate_threshold",
            return_value=sample_lactate_threshold_raw,
        )
        mocker.patch(
            "garmin_cli.endpoints.performance.get_ftp",
            side_effect=[{}, {}],
        )

        result = get_all_thresholds()

        assert result["thresholds"] == [
            {
                "sport": "running",
                "lactateThresholdHeartRate": 168,
                "lactateThresholdPace": "5:12",
                "functionalThresholdPower": None,
                "weight": None,
            }
        ]

    def test_unwraps_value_payload_and_formats_numeric_pace(
        self,
        mocker: Any,
    ) -> None:
        mocker.patch(
            "garmin_cli.endpoints.performance.get_lactate_threshold",
            return_value={
                "value": {
                    "sport": "running",
                    "lactateThresholdHeartRate": 168,
                    "lactateThresholdPace": 250,
                }
            },
        )
        mocker.patch(
            "garmin_cli.endpoints.performance.get_ftp",
            side_effect=[
                {"sport": "cycling", "functionalThresholdPower": 280, "weight": 75.0},
                {"sport": "running", "functionalThresholdPower": 315, "weight": 75.0},
            ],
        )

        result = get_all_thresholds()

        assert result["thresholds"] == [
            {
                "sport": "running",
                "lactateThresholdHeartRate": 168,
                "lactateThresholdPace": "4:10",
                "functionalThresholdPower": 315,
                "weight": 75.0,
            },
            {
                "sport": "cycling",
                "lactateThresholdHeartRate": None,
                "lactateThresholdPace": None,
                "functionalThresholdPower": 280,
                "weight": 75.0,
            },
        ]
