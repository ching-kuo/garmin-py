"""Regression tests for planned serializer fixes."""
from __future__ import annotations

from typing import Any

import pytest

from garmin_cli.serializers import (
    COLUMNS_BODY_BATTERY,
    COLUMNS_CALENDAR_WORKOUT,
    COLUMNS_READINESS,
    COLUMNS_RESTING_HR,
    COLUMNS_SPO2,
    COLUMNS_STATUS,
    COLUMNS_STRESS,
    COLUMNS_VO2MAX,
    COLUMNS_WORKOUT_DETAIL,
    COLUMNS_ZONES,
    serialize_body_battery,
    serialize_calendar_workout,
    serialize_hrv,
    serialize_resting_hr,
    serialize_spo2,
    serialize_stress,
    serialize_thresholds,
    serialize_training_readiness,
    serialize_training_status,
    serialize_vo2max,
    serialize_workout_detail,
    serialize_workout_summary,
    serialize_zones,
)


class TestHrvFieldFallbacks:

    def test_last_night_reads_lastNightAvg_for_single_day(self, sample_hrv_raw: Any) -> None:
        result = serialize_hrv(sample_hrv_raw)
        assert result[0]["last_night"] == 48

    def test_last_night_reads_lastNightAvg_for_range(self) -> None:
        result = serialize_hrv(
            {
                "hrvSummaries": [
                    {
                        "calendarDate": "2026-03-10",
                        "weeklyAvg": 50,
                        "lastNightAvg": 47,
                        "status": "BALANCED",
                    }
                ]
            }
        )
        assert result == [
            {
                "date": "2026-03-10",
                "weekly_avg": 50,
                "last_night": 47,
                "status": "BALANCED",
            }
        ]

    def test_last_night_falls_back_to_lastNight(self) -> None:
        result = serialize_hrv(
            {
                "hrvSummary": {
                    "calendarDate": "2026-03-11",
                    "weeklyAvg": 52,
                    "lastNight": 49,
                    "status": "BALANCED",
                }
            }
        )
        assert result[0]["last_night"] == 49


class TestWorkoutSerializers:

    def test_calendar_serializer_extracts_workout_id(self, sample_calendar_raw: Any) -> None:
        result = serialize_calendar_workout(sample_calendar_raw)
        assert result[0]["id"] == 987654
        assert result[1]["id"] == 987655

    def test_calendar_columns_include_id(self) -> None:
        assert COLUMNS_CALENDAR_WORKOUT == (
            "date",
            "id",
            "name",
            "type",
            "duration_min",
            "description",
        )

    def test_workout_summary_falls_back_to_display_name_and_estimated_duration(
        self,
        sample_workout_alt_raw: Any,
    ) -> None:
        result = serialize_workout_summary(sample_workout_alt_raw)
        assert result == [
            {
                "id": 987654,
                "name": "Tempo Run",
                "sport": "Running",
                "duration_min": 60.0,
                "description": "4x10min at threshold pace",
            }
        ]

    def test_workout_detail_includes_steps_and_summary(self, sample_workout_detail_raw: Any) -> None:
        result = serialize_workout_detail(sample_workout_detail_raw)
        assert result[0]["steps_summary"] == "warmup > interval > cooldown"
        assert result[0]["steps"] == [
            {
                "step_order": 1,
                "step_type": "warmup",
                "duration_type": "time",
                "duration_value": 600,
                "target_type": None,
                "target_value_low": None,
                "target_value_high": None,
            },
            {
                "step_order": 2,
                "step_type": "interval",
                "duration_type": "time",
                "duration_value": 300,
                "target_type": "heart.rate.zone",
                "target_value_low": 160,
                "target_value_high": 170,
            },
            {
                "step_order": 3,
                "step_type": "cooldown",
                "duration_type": "time",
                "duration_value": 600,
                "target_type": None,
                "target_value_low": None,
                "target_value_high": None,
            },
        ]

    def test_workout_detail_handles_missing_segments(self, sample_workout_raw: Any) -> None:
        result = serialize_workout_detail(sample_workout_raw)
        assert result[0]["steps"] == []
        assert result[0]["steps_summary"] == ""

    def test_workout_detail_columns_use_steps_summary(self) -> None:
        assert COLUMNS_WORKOUT_DETAIL == (
            "id",
            "name",
            "sport",
            "duration_min",
            "description",
            "steps_summary",
        )


class TestPerformanceSerializers:

    def test_serialize_vo2max_normalizes_flat_payload(self, sample_vo2max_raw: Any) -> None:
        result = serialize_vo2max(sample_vo2max_raw)
        assert result == [{"date": "2026-03-11", "vo2max": 52.0, "sport": "running"}]

    def test_serialize_vo2max_normalizes_wrapped_payload(self, sample_vo2max_wrapped_raw: Any) -> None:
        result = serialize_vo2max(sample_vo2max_wrapped_raw)
        assert result == [{"date": "2026-03-11", "vo2max": 52.0, "sport": "running"}]

    def test_serialize_vo2max_flattens_live_wrapper_payload(self, sample_vo2max_live_raw: Any) -> None:
        result = serialize_vo2max(sample_vo2max_live_raw)
        assert result == [
            {"date": "2026-03-10", "vo2max": 54.0, "sport": "generic"},
            {"date": "2026-03-10", "vo2max": 55.0, "sport": "cycling"},
        ]

    def test_vo2max_columns_are_normalized(self) -> None:
        assert COLUMNS_VO2MAX == ("date", "vo2max", "sport")

    def test_serialize_zones_normalizes_threshold_payload(self) -> None:
        result = serialize_zones(
            {
                "sport": "running",
                "lactateThresholdHeartRate": 168,
                "lactateThresholdSpeed": 3.2,
            }
        )
        assert result == [{"sport": "running", "lt_hr_bpm": 168, "lt_pace": "5:12"}]

    def test_serialize_zones_preserves_existing_pace_string(self) -> None:
        result = serialize_zones(
            {
                "sport": "running",
                "lactateThresholdHeartRate": 168,
                "lactateThresholdPace": "4:10",
            }
        )
        assert result == [{"sport": "running", "lt_hr_bpm": 168, "lt_pace": "4:10"}]

    def test_zones_columns_are_normalized(self) -> None:
        assert COLUMNS_ZONES == ("sport", "lt_hr_bpm", "lt_pace")

    def test_serialize_zones_merges_live_lactate_payload(
        self,
        sample_lactate_threshold_live_raw: Any,
    ) -> None:
        result = serialize_zones(sample_lactate_threshold_live_raw)
        assert result == [{"sport": "running", "lt_hr_bpm": 177, "lt_pace": "4:26"}]

    def test_serialize_thresholds_formats_numeric_lt_pace(self) -> None:
        result = serialize_thresholds(
            {
                "thresholds": [
                    {
                        "sport": "running",
                        "lactateThresholdHeartRate": 168,
                        "lactateThresholdPace": 250,
                        "functionalThresholdPower": None,
                        "weight": 75.0,
                    }
                ]
            }
        )
        assert result[0]["lt_pace"] == "4:10"


class TestNewHealthSerializers:

    def test_serialize_body_battery(self, sample_body_battery_raw: Any) -> None:
        result = serialize_body_battery(sample_body_battery_raw)
        assert result == [{"date": "2026-03-11", "start_level": 85, "end_level": 60}]
        assert COLUMNS_BODY_BATTERY == ("date", "start_level", "end_level")

    def test_serialize_stress(self, sample_stress_raw: Any) -> None:
        result = serialize_stress(sample_stress_raw)
        assert result == [{"date": "2026-03-11", "avg_stress": 35, "max_stress": 72}]
        assert COLUMNS_STRESS == ("date", "avg_stress", "max_stress")

    def test_serialize_spo2(self, sample_spo2_raw: Any) -> None:
        result = serialize_spo2(sample_spo2_raw)
        assert result == [{"date": "2026-03-11", "avg_spo2": 97, "lowest_spo2": 93}]
        assert COLUMNS_SPO2 == ("date", "avg_spo2", "lowest_spo2")

    def test_serialize_resting_hr(self, sample_resting_hr_raw: Any) -> None:
        result = serialize_resting_hr(sample_resting_hr_raw)
        assert result == [{"date": "2026-03-11", "resting_hr": 52}]
        assert COLUMNS_RESTING_HR == ("date", "resting_hr")

    def test_serialize_training_readiness(self, sample_training_readiness_raw: Any) -> None:
        result = serialize_training_readiness(sample_training_readiness_raw)
        assert result == [{"date": "2026-03-11", "score": 68, "level": "MODERATE"}]
        assert COLUMNS_READINESS == ("date", "score", "level")

    def test_serialize_training_status(self, sample_training_status_raw: Any) -> None:
        result = serialize_training_status(sample_training_status_raw)
        assert result == [
            {
                "date": "2026-03-11",
                "training_status": "PRODUCTIVE",
                "load_type": "OPTIMAL",
            }
        ]
        assert COLUMNS_STATUS == ("date", "training_status", "load_type")
