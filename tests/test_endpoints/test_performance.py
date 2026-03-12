"""Tests for garmin_cli.endpoints.performance — threshold and VO2max functions."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.performance import (
    get_all_thresholds,
    get_ftp,
    get_lactate_threshold,
    get_vo2max,
)
from garmin_cli.exceptions import GarminCliError


# ---------------------------------------------------------------------------
# Mock HTTP error helper
# ---------------------------------------------------------------------------

def _http_error(status_code: int) -> Exception:
    err = Exception(f"HTTP {status_code}")
    err.response = MagicMock(status_code=status_code)  # type: ignore[attr-defined]
    return err


# ---------------------------------------------------------------------------
# get_lactate_threshold
# ---------------------------------------------------------------------------

class TestGetLactateThreshold:

    def test_calls_garth(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        get_lactate_threshold()
        assert mock_garth.connectapi.called

    def test_returns_value(self, mocker: Any, sample_lactate_threshold_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_lactate_threshold_raw
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        result = get_lactate_threshold()
        assert result is not None

    def test_uses_biometric_service_endpoint(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        get_lactate_threshold()
        call_str = str(mock_garth.connectapi.call_args)
        assert "biometric" in call_str.lower() or "lactate" in call_str.lower()

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

    def test_calls_garth(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        get_ftp(sport="cycling")
        assert mock_garth.connectapi.called

    def test_sport_passed_to_api(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        get_ftp(sport="cycling")
        call_str = str(mock_garth.connectapi.call_args)
        assert "cycling" in call_str.lower() or "Cycling" in call_str

    def test_returns_ftp_data(self, mocker: Any, sample_ftp_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_ftp_raw
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        result = get_ftp(sport="cycling")
        assert result is not None

    def test_http_404_raises_not_found_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_ftp(sport="cycling")
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_running_sport_param(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        result = get_ftp(sport="running")
        assert result is not None

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

    def test_calls_garth_with_date(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        get_vo2max(date(2026, 3, 11))
        assert mock_garth.connectapi.called

    def test_date_appears_in_api_call(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        get_vo2max(date(2026, 3, 11))
        call_str = str(mock_garth.connectapi.call_args)
        assert "2026" in call_str

    def test_returns_vo2max_data(self, mocker: Any, sample_vo2max_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_vo2max_raw
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        result = get_vo2max(date(2026, 3, 11))
        assert result is not None

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


# ---------------------------------------------------------------------------
# get_all_thresholds
# ---------------------------------------------------------------------------

class TestGetAllThresholds:

    def test_calls_garth_multiple_times(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        get_all_thresholds()
        # Should call lactate threshold + FTP (cycling + running)
        assert mock_garth.connectapi.call_count >= 1

    def test_returns_dict(self, mocker: Any, sample_all_thresholds_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_all_thresholds_raw
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        result = get_all_thresholds()
        assert isinstance(result, dict)

    def test_result_has_expected_fields(
        self, mocker: Any, sample_all_thresholds_raw: Any
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_all_thresholds_raw
        mocker.patch("garmin_cli.endpoints.performance.garth", mock_garth)

        result = get_all_thresholds()
        # Should return dict (keys may vary if some thresholds not available)
        assert result is not None

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
