"""Endpoint regression tests for plan fixes."""
from __future__ import annotations

from datetime import date
from typing import Any

from garmin_cli.endpoints.health import (
    get_body_battery_range,
    get_resting_hr_range,
    get_spo2_range,
    get_stress_range,
    get_training_readiness_range,
)
from garmin_cli.endpoints.performance import get_all_thresholds, get_latest_vo2max


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


class TestThresholdEndpointNormalization:

    def test_get_all_thresholds_unwraps_value_payload_and_formats_numeric_pace(
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


class TestVo2maxEndpointDefaults:

    def test_get_latest_vo2max_queries_recent_range(self, mocker: Any) -> None:
        mock_request = mocker.patch(
            "garmin_cli.endpoints.performance._request",
            return_value=[],
        )

        get_latest_vo2max()

        call_url = mock_request.call_args[0][0]
        assert "/metrics-service/metrics/maxmet/daily/" in call_url
