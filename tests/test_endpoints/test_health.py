"""Tests for garmin_cli.endpoints.health — all health endpoint functions."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.health import (
    get_body_battery_range,
    get_hrv,
    get_resting_hr_range,
    get_sleep,
    get_spo2_range,
    get_stress_range,
    get_training_readiness_range,
)
from garmin_cli.exceptions import GarminCliError
from tests.helpers import make_http_error as _http_error


# ---------------------------------------------------------------------------
# get_hrv — endpoint routing logic
# ---------------------------------------------------------------------------

class TestGetHrv:

    def test_multi_day_range_uses_daily_range_endpoint(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        get_hrv(date(2026, 3, 1), date(2026, 3, 7))
        call_str = str(mock_garth.connectapi.call_args)
        assert "/hrv-service/hrv/daily/2026-03-01/2026-03-07" in call_str


# ---------------------------------------------------------------------------
# Rate limiting / error handling (strengthened assertions)
# ---------------------------------------------------------------------------

class TestHealthEndpointErrorHandling:

    def test_http_404_raises_garmin_cli_error_with_not_found_code(
        self, mocker: Any
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_sleep(date(2026, 3, 11), date(2026, 3, 11))
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_http_429_raises_rate_limited_error_after_retries(
        self, mocker: Any
    ) -> None:
        mock_garth = MagicMock()
        # 4 calls: 1 initial + 3 retries — all return 429
        mock_garth.connectapi.side_effect = [_http_error(429)] * 4
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
        mocker.patch("time.sleep")  # avoid real delays in tests

        with pytest.raises(GarminCliError) as exc_info:
            get_sleep(date(2026, 3, 11), date(2026, 3, 11))
        assert exc_info.value.error_code == "RATE_LIMITED"

    def test_http_500_raises_server_error_after_retries(
        self, mocker: Any
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [_http_error(500)] * 4
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            get_sleep(date(2026, 3, 11), date(2026, 3, 11))
        assert exc_info.value.error_code == "SERVER_ERROR"

    def test_http_429_retries_before_failing(self, mocker: Any) -> None:
        """Implementation must retry 3 times before giving up on 429."""
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [_http_error(429)] * 4
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
        mock_sleep = mocker.patch("time.sleep")

        with pytest.raises(GarminCliError):
            get_sleep(date(2026, 3, 11), date(2026, 3, 11))

        # Should have called sleep for exponential backoff
        assert mock_sleep.call_count >= 1

    def test_http_429_succeeds_on_retry(self, mocker: Any) -> None:
        """Implementation retries and succeeds on 2nd attempt."""
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [
            _http_error(429),
            {"dailySleepDTO": {}},  # succeeds on retry
        ]
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
        mocker.patch("time.sleep")

        result = get_sleep(date(2026, 3, 11), date(2026, 3, 11))
        assert result is not None

    def test_hrv_404_raises_not_found(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_hrv(date(2026, 3, 11), date(2026, 3, 11))
        assert exc_info.value.error_code == "NOT_FOUND"


class TestDailyHealthRangeHelpers:

    def test_body_battery_range_collects_each_day(self, mocker: Any) -> None:
        mock_get = mocker.patch(
            "garmin_cli.endpoints.health.get_body_battery",
            side_effect=[
                {"bodyBatteryValuesArray": [["2026-03-11T08:00:00", 85, "CHARGED"]]},
                {"bodyBatteryValuesArray": [["2026-03-12T08:00:00", 75, "CHARGED"]]},
            ],
        )
        mock_sleep = mocker.patch("garmin_cli.endpoints._base.time.sleep")

        result = get_body_battery_range(date(2026, 3, 11), date(2026, 3, 12))

        assert result == [
            {"bodyBatteryValuesArray": [["2026-03-11T08:00:00", 85, "CHARGED"]]},
            {"bodyBatteryValuesArray": [["2026-03-12T08:00:00", 75, "CHARGED"]]},
        ]
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(0.5)

    def test_other_range_helpers_reuse_daily_iteration(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.health.get_stress",
            side_effect=[{"avgStressLevel": 35}, {"avgStressLevel": 40}],
        )
        mocker.patch(
            "garmin_cli.endpoints.health.get_spo2",
            side_effect=[{"averageSpO2": 97}, {"averageSpO2": 96}],
        )
        mocker.patch(
            "garmin_cli.endpoints.health.get_resting_hr",
            side_effect=[{"restingHeartRateValue": 52}, {"restingHeartRateValue": 51}],
        )
        mocker.patch(
            "garmin_cli.endpoints.health.get_training_readiness",
            side_effect=[{"score": 68}, {"score": 70}],
        )
        mocker.patch("garmin_cli.endpoints._base.time.sleep")

        assert len(get_stress_range(date(2026, 3, 11), date(2026, 3, 12))) == 2
        assert len(get_spo2_range(date(2026, 3, 11), date(2026, 3, 12))) == 2
        assert len(get_resting_hr_range(date(2026, 3, 11), date(2026, 3, 12))) == 2
        assert len(get_training_readiness_range(date(2026, 3, 11), date(2026, 3, 12))) == 2
