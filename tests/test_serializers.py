"""Tests for garmin_cli.serializers — all serialize_* functions and COLUMNS."""
from __future__ import annotations

from typing import Any

import pytest

from garmin_cli.serializers import (
    COLUMNS_ACTIVITY_SUMMARY,
    COLUMNS_BODY_BATTERY,
    COLUMNS_CALENDAR_WORKOUT,
    COLUMNS_HRV,
    COLUMNS_MULTISPORT_CHILDREN,
    COLUMNS_READINESS,
    COLUMNS_RESTING_HR,
    COLUMNS_SLEEP,
    COLUMNS_SPO2,
    COLUMNS_STATUS,
    COLUMNS_STRESS,
    COLUMNS_THRESHOLDS,
    COLUMNS_VO2MAX,
    COLUMNS_WEIGHT,
    COLUMNS_ZONES,
    serialize_activity_summary,
    serialize_body_battery,
    serialize_calendar_workout,
    serialize_hrv,
    serialize_multisport_children,
    serialize_resting_hr,
    serialize_sleep,
    serialize_spo2,
    serialize_stress,
    serialize_thresholds,
    serialize_training_readiness,
    serialize_training_status,
    serialize_vo2max,
    serialize_weight,
    serialize_workout_detail,
    serialize_workout_summary,
    select_latest_dated_rows,
    serialize_zones,
)


# ---------------------------------------------------------------------------
# select_latest_dated_rows
# ---------------------------------------------------------------------------


class TestSelectLatestDatedRows:

    def test_returns_only_latest_date_rows(self) -> None:
        rows: list[dict[str, object]] = [
            {"date": "2026-03-10", "vo2max": 54.0, "sport": "generic"},
            {"date": "2026-03-10", "vo2max": 55.0, "sport": "cycling"},
            {"date": "2026-03-08", "vo2max": 52.0, "sport": "generic"},
        ]
        assert select_latest_dated_rows(rows) == rows[:2]

    def test_empty_input_returns_empty(self) -> None:
        assert select_latest_dated_rows([]) == []

    def test_no_dated_rows_returns_first(self) -> None:
        rows: list[dict[str, object]] = [{"vo2max": 52.0}, {"vo2max": 50.0}]
        assert select_latest_dated_rows(rows) == [rows[0]]

    def test_single_row_returned(self) -> None:
        rows: list[dict[str, object]] = [{"date": "2026-03-11", "vo2max": 52.0}]
        assert select_latest_dated_rows(rows) == rows


# ---------------------------------------------------------------------------
# serialize_sleep
# ---------------------------------------------------------------------------

class TestSerializeSleep:

    def test_returns_list(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert isinstance(result, list)

    def test_single_day_returns_one_item(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert len(result) == 1

    def test_date_value_correct(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert result[0]["date"] == "2026-03-11"

    def test_duration_hours_correct(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        # 27000 seconds / 3600 = 7.5 hours
        assert result[0]["duration_hours"] == pytest.approx(7.5, rel=0.01)

    def test_deep_min_correct(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        # 5400 seconds / 60 = 90 minutes
        assert result[0]["deep_min"] == pytest.approx(90, rel=0.01)

    def test_score_value(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert result[0]["score"] == 82

    def test_missing_score_returns_none(self) -> None:
        raw = {"dailySleepDTO": {"calendarDate": "2026-03-11", "sleepTimeSeconds": 3600}}
        result = serialize_sleep(raw)
        assert result[0]["score"] is None

    def test_missing_keys_return_none_not_crash(self) -> None:
        result = serialize_sleep({})
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["date"] is None or result[0].get("date") is None

    def test_multi_day_returns_multiple_items(self, sample_sleep_multi_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_multi_raw)
        assert len(result) == 2

    def test_multi_day_each_item_has_required_keys(self, sample_sleep_multi_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_multi_raw)
        for item in result:
            for key in ("date", "duration_hours", "deep_min", "light_min", "rem_min", "awake_min", "score"):
                assert key in item

# ---------------------------------------------------------------------------
# serialize_hrv
# ---------------------------------------------------------------------------

class TestSerializeHrv:

    def test_contains_date(self, sample_hrv_raw: Any) -> None:
        result = serialize_hrv(sample_hrv_raw)
        assert result[0]["date"] == "2026-03-11"

    def test_weekly_avg_present(self, sample_hrv_raw: Any) -> None:
        result = serialize_hrv(sample_hrv_raw)
        assert "weekly_avg" in result[0]
        assert result[0]["weekly_avg"] == 52

    def test_last_night_present(self, sample_hrv_raw: Any) -> None:
        result = serialize_hrv(sample_hrv_raw)
        assert "last_night" in result[0]
        assert result[0]["last_night"] == 48

    def test_status_present(self, sample_hrv_raw: Any) -> None:
        result = serialize_hrv(sample_hrv_raw)
        assert "status" in result[0]
        assert result[0]["status"] == "BALANCED"

    def test_missing_keys_return_none(self) -> None:
        result = serialize_hrv({})
        assert result == []

    def test_missing_hrv_summary_returns_empty_list(self) -> None:
        result = serialize_hrv({"foo": "bar"})
        assert result == []

    def test_range_payload_returns_multiple_rows(self) -> None:
        result = serialize_hrv(
            {
                "hrvSummaries": [
                    {
                        "calendarDate": "2026-03-10",
                        "weeklyAvg": 50,
                        "lastNight": 48,
                        "status": "BALANCED",
                    },
                    {
                        "calendarDate": "2026-03-11",
                        "weeklyAvg": 51,
                        "lastNight": 49,
                        "status": "BALANCED",
                    },
                ]
            }
        )
        assert result == [
            {
                "date": "2026-03-10",
                "weekly_avg": 50,
                "last_night": 48,
                "status": "BALANCED",
            },
            {
                "date": "2026-03-11",
                "weekly_avg": 51,
                "last_night": 49,
                "status": "BALANCED",
            },
        ]

    def test_range_payload_prefers_last_night_avg_when_available(self) -> None:
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

# ---------------------------------------------------------------------------
# serialize_weight
# ---------------------------------------------------------------------------

class TestSerializeWeight:

    def test_contains_date(self, sample_weight_raw: Any) -> None:
        result = serialize_weight(sample_weight_raw)
        assert result[0]["date"] == "2026-03-11"

    def test_weight_kg_converted_from_grams(self, sample_weight_raw: Any) -> None:
        result = serialize_weight(sample_weight_raw)
        # 75000g -> 75.0 kg
        assert result[0]["weight_kg"] == pytest.approx(75.0, rel=0.01)

    def test_bmi_present(self, sample_weight_raw: Any) -> None:
        result = serialize_weight(sample_weight_raw)
        assert "bmi" in result[0]
        assert result[0]["bmi"] == pytest.approx(23.5, rel=0.01)

    def test_body_fat_pct_present(self, sample_weight_raw: Any) -> None:
        result = serialize_weight(sample_weight_raw)
        assert "body_fat_pct" in result[0]
        assert result[0]["body_fat_pct"] == pytest.approx(18.2, rel=0.01)

    def test_missing_weight_list_returns_empty(self) -> None:
        result = serialize_weight({})
        assert isinstance(result, list)

# ---------------------------------------------------------------------------
# serialize_activity_summary
# ---------------------------------------------------------------------------

class TestSerializeActivitySummary:

    def test_singleton_wraps_in_list(self, sample_activity_raw: Any) -> None:
        result = serialize_activity_summary(sample_activity_raw)
        assert len(result) == 1

    def test_list_input_returns_multiple(self, sample_activities_list_raw: Any) -> None:
        result = serialize_activity_summary(sample_activities_list_raw)
        assert len(result) == 2

    def test_id_present(self, sample_activity_raw: Any) -> None:
        result = serialize_activity_summary(sample_activity_raw)
        assert result[0]["id"] == 12345678

    def test_date_present(self, sample_activity_raw: Any) -> None:
        result = serialize_activity_summary(sample_activity_raw)
        assert "date" in result[0]

    def test_name_present(self, sample_activity_raw: Any) -> None:
        result = serialize_activity_summary(sample_activity_raw)
        assert result[0]["name"] == "Morning Run"

    def test_type_present(self, sample_activity_raw: Any) -> None:
        result = serialize_activity_summary(sample_activity_raw)
        assert result[0]["type"] == "running"

    def test_distance_km_converted(self, sample_activity_raw: Any) -> None:
        result = serialize_activity_summary(sample_activity_raw)
        # 10000m -> 10.0 km
        assert result[0]["distance_km"] == pytest.approx(10.0, rel=0.01)

    def test_duration_min_converted(self, sample_activity_raw: Any) -> None:
        result = serialize_activity_summary(sample_activity_raw)
        # 3600s -> 60.0 min
        assert result[0]["duration_min"] == pytest.approx(60.0, rel=0.01)

    def test_avg_hr_present(self, sample_activity_raw: Any) -> None:
        result = serialize_activity_summary(sample_activity_raw)
        assert result[0]["avg_hr"] == 155

    def test_missing_keys_return_none(self) -> None:
        result = serialize_activity_summary({})
        assert isinstance(result, list)
        assert result[0].get("id") is None

    def test_summary_dto_fallback(self) -> None:
        """Child activities fetched directly should use summaryDTO fallback."""
        raw = {
            "activityId": 18878956185,
            "activityName": "Running",
            "activityType": {"typeKey": "running"},
            "summaryDTO": {
                "startTimeLocal": "2026-04-06T14:30:00",
                "distance": 35049.1,
                "duration": 11888.1,
                "averageHR": 160,
            },
        }
        result = serialize_activity_summary(raw)
        assert result[0]["id"] == 18878956185
        assert result[0]["date"] == "2026-04-06T14:30:00"
        assert result[0]["distance_km"] == pytest.approx(35.0491, rel=0.01)
        assert result[0]["duration_min"] == pytest.approx(198.135, rel=0.01)
        assert result[0]["avg_hr"] == 160

    def test_top_level_fields_preferred_over_summary_dto(self) -> None:
        """Top-level fields take precedence over summaryDTO."""
        raw = {
            "activityId": 1,
            "startTimeLocal": "2026-04-06T06:00:00",
            "distance": 10000.0,
            "duration": 3600.0,
            "averageHR": 150,
            "summaryDTO": {
                "startTimeLocal": "2026-04-06T06:00:01",
                "distance": 9999.0,
                "duration": 3599.0,
                "averageHR": 149,
            },
        }
        result = serialize_activity_summary(raw)
        assert result[0]["date"] == "2026-04-06T06:00:00"
        assert result[0]["distance_km"] == pytest.approx(10.0, rel=0.01)
        assert result[0]["duration_min"] == pytest.approx(60.0, rel=0.01)
        assert result[0]["avg_hr"] == 150

    def test_hybrid_top_level_and_summary_dto(self) -> None:
        """Per-field coalescing uses top-level when present, summaryDTO otherwise."""
        raw = {
            "activityId": 2,
            "startTimeLocal": "2026-04-06T14:00:00",
            "averageHR": 162,
            "activityType": {"typeKey": "running"},
            "summaryDTO": {
                "distance": 35049.1,
                "duration": 11888.1,
                "averageHR": 999,
            },
        }
        result = serialize_activity_summary(raw)
        assert result[0]["date"] == "2026-04-06T14:00:00"
        assert result[0]["distance_km"] == pytest.approx(35.0491, rel=0.01)
        assert result[0]["duration_min"] == pytest.approx(198.135, rel=0.01)
        assert result[0]["avg_hr"] == 162


# ---------------------------------------------------------------------------
# serialize_multisport_children
# ---------------------------------------------------------------------------

class TestSerializeMultisportChildren:

    def test_returns_child_rows(self, sample_multisport_children_raw: Any) -> None:
        result = serialize_multisport_children(sample_multisport_children_raw)
        assert len(result) == 3

    def test_sport_field_present(self, sample_multisport_children_raw: Any) -> None:
        result = serialize_multisport_children(sample_multisport_children_raw)
        assert result[0]["sport"] == "open_water_swimming"
        assert result[1]["sport"] == "cycling"
        assert result[2]["sport"] == "running"

    def test_distance_converted_to_km(self, sample_multisport_children_raw: Any) -> None:
        result = serialize_multisport_children(sample_multisport_children_raw)
        assert result[0]["distance_km"] == pytest.approx(1.5, rel=0.01)
        assert result[1]["distance_km"] == pytest.approx(40.0, rel=0.01)

    def test_duration_converted_to_minutes(self, sample_multisport_children_raw: Any) -> None:
        result = serialize_multisport_children(sample_multisport_children_raw)
        assert result[0]["duration_min"] == pytest.approx(30.0, rel=0.01)
        assert result[1]["duration_min"] == pytest.approx(70.0, rel=0.01)

    def test_avg_hr_present(self, sample_multisport_children_raw: Any) -> None:
        result = serialize_multisport_children(sample_multisport_children_raw)
        assert result[0]["avg_hr"] == 145

    def test_calories_present(self, sample_multisport_children_raw: Any) -> None:
        result = serialize_multisport_children(sample_multisport_children_raw)
        assert result[0]["calories"] == 350

    def test_empty_list(self) -> None:
        assert serialize_multisport_children([]) == []

    def test_skips_non_dict_items(self) -> None:
        result = serialize_multisport_children([None, "bad", 123])
        assert result == []

    def test_summary_dto_fallback(self) -> None:
        children = [
            {
                "activityId": 1,
                "activityName": "Swim",
                "activityType": {"typeKey": "swimming"},
                "summaryDTO": {
                    "distance": 1500.0,
                    "duration": 1800.0,
                    "averageHR": 140,
                    "averageSpeed": 0.833,
                    "calories": 300,
                },
            }
        ]
        result = serialize_multisport_children(children)
        assert result[0]["distance_km"] == pytest.approx(1.5, rel=0.01)
        assert result[0]["avg_hr"] == 140

# ---------------------------------------------------------------------------
# serialize_calendar_workout
# ---------------------------------------------------------------------------

class TestSerializeCalendarWorkout:

    def test_returns_multiple_items(self, sample_calendar_raw: Any) -> None:
        result = serialize_calendar_workout(sample_calendar_raw)
        assert len(result) == 2

    def test_date_present(self, sample_calendar_raw: Any) -> None:
        result = serialize_calendar_workout(sample_calendar_raw)
        assert result[0]["date"] == "2026-03-12"

    def test_id_present(self, sample_calendar_raw: Any) -> None:
        result = serialize_calendar_workout(sample_calendar_raw)
        assert result[0]["id"] == 987654

    def test_name_present(self, sample_calendar_raw: Any) -> None:
        result = serialize_calendar_workout(sample_calendar_raw)
        assert result[0]["name"] == "Tempo Run"

    def test_type_present(self, sample_calendar_raw: Any) -> None:
        result = serialize_calendar_workout(sample_calendar_raw)
        assert result[0]["type"] == "running"

    def test_duration_min_converted(self, sample_calendar_raw: Any) -> None:
        result = serialize_calendar_workout(sample_calendar_raw)
        # 3600s -> 60 min
        assert result[0]["duration_min"] == pytest.approx(60.0, rel=0.01)

    def test_description_present(self, sample_calendar_raw: Any) -> None:
        result = serialize_calendar_workout(sample_calendar_raw)
        assert result[0]["description"] == "Hard effort"

    def test_empty_calendar_items_returns_empty_list(self) -> None:
        result = serialize_calendar_workout({"calendarItems": []})
        assert result == []

    def test_missing_raw_returns_empty_list(self) -> None:
        result = serialize_calendar_workout({})
        assert isinstance(result, list)

# ---------------------------------------------------------------------------
# serialize_thresholds
# ---------------------------------------------------------------------------

class TestSerializeThresholds:

    def test_returns_two_items(self, sample_all_thresholds_raw: Any) -> None:
        result = serialize_thresholds(sample_all_thresholds_raw)
        assert len(result) == 2

    def test_sport_present(self, sample_all_thresholds_raw: Any) -> None:
        result = serialize_thresholds(sample_all_thresholds_raw)
        assert result[0]["sport"] == "running"

    def test_lt_hr_bpm_present(self, sample_all_thresholds_raw: Any) -> None:
        result = serialize_thresholds(sample_all_thresholds_raw)
        assert result[0]["lt_hr_bpm"] == 168

    def test_lt_pace_present(self, sample_all_thresholds_raw: Any) -> None:
        result = serialize_thresholds(sample_all_thresholds_raw)
        assert result[0]["lt_pace"] == "5:12"

    def test_ftp_watts_present_cycling(self, sample_all_thresholds_raw: Any) -> None:
        result = serialize_thresholds(sample_all_thresholds_raw)
        cycling = next(r for r in result if r["sport"] == "cycling")
        assert cycling["ftp_watts"] == 280

    def test_ftp_watts_none_for_running(self, sample_all_thresholds_raw: Any) -> None:
        result = serialize_thresholds(sample_all_thresholds_raw)
        running = next(r for r in result if r["sport"] == "running")
        assert running["ftp_watts"] is None

    def test_weight_kg_present(self, sample_all_thresholds_raw: Any) -> None:
        result = serialize_thresholds(sample_all_thresholds_raw)
        assert result[0]["weight_kg"] == 75.0

    def test_missing_keys_return_none(self) -> None:
        result = serialize_thresholds({"thresholds": [{}]})
        assert isinstance(result, list)
        assert result[0].get("sport") is None

    def test_numeric_lt_pace_is_formatted(self) -> None:
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

class TestWorkoutSerializers:

    def test_workout_summary_uses_display_name_and_estimated_duration(
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

    def test_workout_detail_includes_steps_and_summary(
        self,
        sample_workout_detail_raw: Any,
    ) -> None:
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


class TestPerformanceSerializers:

    def test_serialize_vo2max_supports_flat_and_wrapped_payloads(
        self,
        sample_vo2max_raw: Any,
        sample_vo2max_wrapped_raw: Any,
    ) -> None:
        expected = [{"date": "2026-03-11", "vo2max": 52.0, "sport": "running"}]
        assert serialize_vo2max(sample_vo2max_raw) == expected
        assert serialize_vo2max(sample_vo2max_wrapped_raw) == expected

    def test_serialize_vo2max_flattens_live_wrapper_payload(self, sample_vo2max_live_raw: Any) -> None:
        assert serialize_vo2max(sample_vo2max_live_raw) == [
            {"date": "2026-03-10", "vo2max": 54.0, "sport": "generic"},
            {"date": "2026-03-10", "vo2max": 55.0, "sport": "cycling"},
        ]
        assert COLUMNS_VO2MAX == ("date", "vo2max", "sport")

    def test_serialize_zones_normalizes_speed_and_preserves_pace_string(self) -> None:
        assert serialize_zones(
            {
                "sport": "running",
                "lactateThresholdHeartRate": 168,
                "lactateThresholdSpeed": 3.2,
            }
        ) == [{"sport": "running", "lt_hr_bpm": 168, "lt_pace": "5:12"}]
        assert serialize_zones(
            {
                "sport": "running",
                "lactateThresholdHeartRate": 168,
                "lactateThresholdPace": "4:10",
            }
        ) == [{"sport": "running", "lt_hr_bpm": 168, "lt_pace": "4:10"}]
        assert COLUMNS_ZONES == ("sport", "lt_hr_bpm", "lt_pace")

    def test_serialize_zones_merges_live_lactate_payload(
        self,
        sample_lactate_threshold_live_raw: Any,
    ) -> None:
        assert serialize_zones(sample_lactate_threshold_live_raw) == [
            {"sport": "running", "lt_hr_bpm": 177, "lt_pace": "4:26"}
        ]


@pytest.mark.parametrize(
    ("serializer", "payload_fixture", "expected", "columns", "required_columns"),
    [
        (
            serialize_body_battery,
            "sample_body_battery_raw",
            {"date": "2026-03-11", "start_level": 85, "end_level": 60},
            COLUMNS_BODY_BATTERY,
            ("date", "start_level", "end_level"),
        ),
        (
            serialize_stress,
            "sample_stress_raw",
            {"date": "2026-03-11", "avg_stress": 35, "max_stress": 72},
            COLUMNS_STRESS,
            ("date", "avg_stress", "max_stress"),
        ),
        (
            serialize_spo2,
            "sample_spo2_raw",
            {"date": "2026-03-11", "avg_spo2": 97, "lowest_spo2": 93},
            COLUMNS_SPO2,
            ("date", "avg_spo2", "lowest_spo2"),
        ),
        (
            serialize_resting_hr,
            "sample_resting_hr_raw",
            {"date": "2026-03-11", "resting_hr": 52},
            COLUMNS_RESTING_HR,
            ("date", "resting_hr"),
        ),
        (
            serialize_training_readiness,
            "sample_training_readiness_raw",
            {"date": "2026-03-11", "score": 68, "level": "MODERATE"},
            COLUMNS_READINESS,
            ("date", "score", "level"),
        ),
        (
            serialize_training_status,
            "sample_training_status_raw",
            {
                "date": "2026-03-11",
                "training_status": "PRODUCTIVE",
                "load_type": "OPTIMAL",
            },
            COLUMNS_STATUS,
            ("date", "training_status", "load_type"),
        ),
    ],
)
def test_additional_health_serializers(
    request: pytest.FixtureRequest,
    serializer: Any,
    payload_fixture: str,
    expected: dict[str, Any],
    columns: tuple[str, ...],
    required_columns: tuple[str, ...],
) -> None:
    payload = request.getfixturevalue(payload_fixture)
    assert serializer(payload) == [expected]
    assert columns == required_columns


# ---------------------------------------------------------------------------
# serialize_activity_detail
# ---------------------------------------------------------------------------

class TestSerializeActivityDetail:

    def test_cycling_all_power_cadence_elevation(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 1,
            "startTimeLocal": "2026-04-01T08:00:00",
            "activityName": "Morning Ride",
            "activityType": {"typeKey": "cycling"},
            "distance": 50000.0,
            "duration": 5400.0,
            "averageHR": 145,
            "maxHR": 178,
            "calories": 850,
            "elevationGain": 600.0,
            "elevationLoss": 580.0,
            "averageSpeed": 9.259,
            "maxSpeed": 15.0,
            "averageBikingCadenceInRevPerMinute": 85.0,
            "averagePower": 210.0,
            "maxPower": 650.0,
            "normPower": 230.0,
            "trainingStressScore": 120.5,
            "intensityFactor": 0.92,
        }
        result = serialize_activity_detail(raw)
        assert len(result) == 1
        row = result[0]
        # base fields
        assert row["id"] == 1
        assert row["name"] == "Morning Ride"
        assert row["type"] == "cycling"
        assert row["distance_km"] == pytest.approx(50.0, rel=0.01)
        assert row["duration_min"] == pytest.approx(90.0, rel=0.01)
        assert row["avg_hr"] == 145
        # extended fields
        assert row["max_hr"] == 178
        assert row["calories"] == 850
        assert row["elevation_gain_m"] == pytest.approx(600.0, rel=0.01)
        assert row["elevation_loss_m"] == pytest.approx(580.0, rel=0.01)
        assert row["avg_speed_kmh"] == pytest.approx(9.259 * 3.6, rel=0.01)
        assert row["max_speed_kmh"] == pytest.approx(15.0 * 3.6, rel=0.01)
        assert row["avg_cadence_rpm"] == pytest.approx(85.0, rel=0.01)
        assert row["avg_cadence_spm"] is None
        assert row["avg_power_w"] == pytest.approx(210.0, rel=0.01)
        assert row["max_power_w"] == pytest.approx(650.0, rel=0.01)
        assert row["norm_power_w"] == pytest.approx(230.0, rel=0.01)
        assert row["tss"] == pytest.approx(120.5, rel=0.01)
        assert row["intensity_factor"] == pytest.approx(0.92, rel=0.01)

    def test_running_cadence_spm_no_power(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 2,
            "startTimeLocal": "2026-04-02T06:00:00",
            "activityName": "Easy Run",
            "activityType": {"typeKey": "running"},
            "distance": 10000.0,
            "duration": 3600.0,
            "averageHR": 150,
            "maxHR": 170,
            "calories": 600,
            "averageRunningCadenceInStepsPerMinute": 180.0,
        }
        result = serialize_activity_detail(raw)
        row = result[0]
        assert row["avg_cadence_spm"] == pytest.approx(180.0, rel=0.01)
        assert row["avg_cadence_rpm"] is None
        assert row["avg_power_w"] is None
        assert row["max_power_w"] is None
        assert row["norm_power_w"] is None

    def test_no_extended_fields_returns_nulls(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 3,
            "startTimeLocal": "2026-04-03T10:00:00",
            "activityName": "Walk",
            "activityType": {"typeKey": "walking"},
        }
        result = serialize_activity_detail(raw)
        assert len(result) == 1
        row = result[0]
        assert row["max_hr"] is None
        assert row["calories"] is None
        assert row["elevation_gain_m"] is None
        assert row["elevation_loss_m"] is None
        assert row["avg_speed_kmh"] is None
        assert row["max_speed_kmh"] is None
        assert row["avg_cadence_spm"] is None
        assert row["avg_cadence_rpm"] is None
        assert row["avg_power_w"] is None
        assert row["max_power_w"] is None
        assert row["norm_power_w"] is None
        assert row["tss"] is None
        assert row["intensity_factor"] is None

    def test_summary_dto_fallback_for_extended_fields(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 4,
            "activityName": "Ride",
            "activityType": {"typeKey": "cycling"},
            "summaryDTO": {
                "startTimeLocal": "2026-04-04T07:00:00",
                "distance": 20000.0,
                "duration": 3600.0,
                "averageHR": 140,
                "maxHR": 175,
                "calories": 500,
                "elevationGain": 200.0,
                "elevationLoss": 190.0,
                "averageSpeed": 5.556,
                "maxSpeed": 12.0,
                "averageBikingCadenceInRevPerMinute": 80.0,
                "averagePower": 180.0,
                "maxPower": 400.0,
                "normPower": 200.0,
                "trainingStressScore": 80.0,
                "intensityFactor": 0.85,
            },
        }
        result = serialize_activity_detail(raw)
        row = result[0]
        assert row["max_hr"] == 175
        assert row["calories"] == 500
        assert row["elevation_gain_m"] == pytest.approx(200.0, rel=0.01)
        assert row["avg_speed_kmh"] == pytest.approx(5.556 * 3.6, rel=0.01)
        assert row["avg_power_w"] == pytest.approx(180.0, rel=0.01)
        assert row["tss"] == pytest.approx(80.0, rel=0.01)

    def test_top_level_preferred_over_summary_dto_for_extended(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 10,
            "activityType": {"typeKey": "cycling"},
            "maxHR": 185,
            "calories": 900,
            "elevationGain": 300.0,
            "averageSpeed": 8.0,
            "averagePower": 250.0,
            "summaryDTO": {
                "maxHR": 170,
                "calories": 800,
                "elevationGain": 200.0,
                "averageSpeed": 6.0,
                "averagePower": 200.0,
            },
        }
        result = serialize_activity_detail(raw)
        row = result[0]
        assert row["max_hr"] == 185
        assert row["calories"] == 900
        assert row["elevation_gain_m"] == pytest.approx(300.0, rel=0.01)
        assert row["avg_speed_kmh"] == pytest.approx(8.0 * 3.6, rel=0.01)
        assert row["avg_power_w"] == pytest.approx(250.0, rel=0.01)

    def test_hybrid_top_level_and_summary_dto_for_extended(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 11,
            "activityType": {"typeKey": "cycling"},
            "maxHR": 185,
            "averagePower": 250.0,
            "summaryDTO": {
                "calories": 800,
                "elevationGain": 200.0,
                "averageSpeed": 6.0,
            },
        }
        result = serialize_activity_detail(raw)
        row = result[0]
        assert row["max_hr"] == 185
        assert row["calories"] == 800
        assert row["elevation_gain_m"] == pytest.approx(200.0, rel=0.01)
        assert row["avg_speed_kmh"] == pytest.approx(6.0 * 3.6, rel=0.01)
        assert row["avg_power_w"] == pytest.approx(250.0, rel=0.01)

    def test_speed_zero_converts_to_zero(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 5,
            "activityType": {"typeKey": "running"},
            "averageSpeed": 0.0,
            "maxSpeed": 0.0,
        }
        result = serialize_activity_detail(raw)
        assert result[0]["avg_speed_kmh"] == pytest.approx(0.0)
        assert result[0]["max_speed_kmh"] == pytest.approx(0.0)

    def test_speed_null_stays_null(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 6,
            "activityType": {"typeKey": "running"},
        }
        result = serialize_activity_detail(raw)
        assert result[0]["avg_speed_kmh"] is None
        assert result[0]["max_speed_kmh"] is None

    def test_columns_activity_detail_exists(self) -> None:
        from garmin_cli.serializers import COLUMNS_ACTIVITY_DETAIL
        for col in (
            "id", "date", "name", "type", "distance_km", "duration_min", "avg_hr",
            "max_hr", "calories", "elevation_gain_m", "elevation_loss_m",
            "avg_speed_kmh", "max_speed_kmh",
            "avg_cadence_spm", "avg_cadence_rpm",
            "avg_power_w", "max_power_w", "norm_power_w",
            "tss", "intensity_factor",
        ):
            assert col in COLUMNS_ACTIVITY_DETAIL


# ---------------------------------------------------------------------------
# Sport-aware activity detail (U4): union schema + sport-specific projection
# ---------------------------------------------------------------------------


class TestSportAwareActivityDetail:
    """Detail rows must contain every UNION_COLUMNS key regardless of sport."""

    def test_cycling_row_has_union_keys_with_running_swim_as_none(self) -> None:
        from garmin_cli.serializers import COLUMNS_ACTIVITY_DETAIL, serialize_activity_detail
        raw = {
            "activityId": 100,
            "activityType": {"typeKey": "cycling"},
            "averagePower": 220.0,
            "normPower": 240.0,
        }
        row = serialize_activity_detail(raw)[0]
        # every union column is present
        assert set(row.keys()) == set(COLUMNS_ACTIVITY_DETAIL)
        # cycling values populated
        assert row["avg_power_w"] == pytest.approx(220.0)
        assert row["norm_power_w"] == pytest.approx(240.0)
        # running-only & swim-only keys are present but null
        for key in ("avg_ground_contact_time", "avg_vertical_oscillation",
                    "avg_stride_length", "swolf", "total_strokes"):
            assert key in row
            assert row[key] is None

    def test_running_projects_running_dynamics(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 200,
            "activityType": {"typeKey": "running"},
            "averageRunningCadenceInStepsPerMinute": 180.0,
            "avgGroundContactTime": 240,
            "avgVerticalOscillation": 8.4,
            "avgVerticalRatio": 6.5,
            "avgStrideLength": 132.0,
            "aerobicTrainingEffect": 3.2,
            "anaerobicTrainingEffect": 1.4,
        }
        row = serialize_activity_detail(raw)[0]
        assert row["avg_cadence_spm"] == pytest.approx(180.0)
        assert row["avg_ground_contact_time"] == 240
        assert row["avg_vertical_oscillation"] == pytest.approx(8.4)
        assert row["avg_vertical_ratio"] == pytest.approx(6.5)
        assert row["avg_stride_length"] == pytest.approx(132.0)
        assert row["aerobic_training_effect"] == pytest.approx(3.2)
        assert row["anaerobic_training_effect"] == pytest.approx(1.4)
        # cycling power should remain null
        assert row["avg_power_w"] is None
        assert row["norm_power_w"] is None
        assert row["tss"] is None

    def test_lap_swim_projects_swim_metrics(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 300,
            "activityType": {"typeKey": "lap_swimming"},
            "avgSwolf": 38,
            "strokes": 720,
            "averageStrokeRate": 28.5,
            "avgStrokeDistance": 1.85,
        }
        row = serialize_activity_detail(raw)[0]
        assert row["swolf"] == 38
        assert row["total_strokes"] == 720
        assert row["avg_stroke_rate"] == pytest.approx(28.5)
        assert row["distance_per_stroke"] == pytest.approx(1.85)
        # cycling/running keys remain null
        assert row["avg_power_w"] is None
        assert row["avg_ground_contact_time"] is None

    def test_summary_dto_fallback_for_running_dynamics(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 201,
            "activityType": {"typeKey": "running"},
            "summaryDTO": {
                "avgGroundContactTime": 250,
                "avgVerticalOscillation": 9.0,
            },
        }
        row = serialize_activity_detail(raw)[0]
        assert row["avg_ground_contact_time"] == 250
        assert row["avg_vertical_oscillation"] == pytest.approx(9.0)

    def test_unknown_sport_falls_back_to_universal_only(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {
            "activityId": 999,
            "activityType": {"typeKey": "weightlifting"},
            "calories": 200,
            "maxHR": 150,
        }
        row = serialize_activity_detail(raw)[0]
        # universal keys populated
        assert row["calories"] == 200
        assert row["max_hr"] == 150
        # sport-specific keys remain null
        assert row["avg_power_w"] is None
        assert row["avg_ground_contact_time"] is None
        assert row["swolf"] is None

    def test_missing_activity_type_uses_default(self) -> None:
        from garmin_cli.serializers import serialize_activity_detail
        raw = {"activityId": 1, "calories": 100}
        row = serialize_activity_detail(raw)[0]
        assert row["calories"] == 100
        # all sport-specific keys are present and null
        assert row["avg_power_w"] is None
        assert row["swolf"] is None


class TestColumnsForSportInSerializers:

    def test_columns_for_sport_importable_from_serializers(self) -> None:
        from garmin_cli.serializers import columns_for_sport
        cycling_cols = columns_for_sport("cycling")
        assert "avg_power_w" in cycling_cols
        assert "avg_ground_contact_time" not in cycling_cols


# ---------------------------------------------------------------------------
# Activity laps serializer (U7)
# ---------------------------------------------------------------------------


class TestSerializeActivityLaps:

    def test_cycling_laps_populate_power_columns(self) -> None:
        from garmin_cli.serializers import serialize_activity_laps
        activity = {"activityType": {"typeKey": "cycling"}}
        splits = {
            "lapDTOs": [
                {
                    "duration": 600.0, "distance": 5000.0,
                    "averageHR": 145, "maxHR": 165,
                    "averagePower": 220, "maxPower": 480, "normalizedPower": 235,
                },
                {
                    "duration": 540.0, "distance": 4500.0,
                    "averageHR": 152, "maxHR": 172,
                    "averagePower": 240, "maxPower": 510, "normalizedPower": 250,
                },
            ],
        }
        rows = serialize_activity_laps(activity, splits)
        assert len(rows) == 2
        assert rows[0]["lap_index"] == 1
        assert rows[1]["lap_index"] == 2
        assert rows[0]["avg_power_w"] == 220
        assert rows[0]["norm_power_w"] == 235
        assert rows[0]["distance_km"] == pytest.approx(5.0, rel=0.01)
        assert rows[0]["duration_min"] == pytest.approx(10.0, rel=0.01)
        # running fields are present but null for cycling laps
        for key in ("avg_ground_contact_time", "avg_vertical_oscillation",
                    "avg_vertical_ratio", "avg_stride_length"):
            assert key in rows[0]
            assert rows[0][key] is None

    def test_running_laps_populate_dynamics_columns(self) -> None:
        from garmin_cli.serializers import serialize_activity_laps
        activity = {"activityType": {"typeKey": "running"}}
        splits = {
            "lapDTOs": [
                {
                    "duration": 480.0, "distance": 1000.0,
                    "averageHR": 162, "maxHR": 175,
                    "avgGroundContactTime": 235, "avgVerticalOscillation": 8.2,
                    "avgVerticalRatio": 6.1, "avgStrideLength": 130.0,
                },
            ],
        }
        rows = serialize_activity_laps(activity, splits)
        assert len(rows) == 1
        row = rows[0]
        assert row["avg_ground_contact_time"] == 235
        assert row["avg_vertical_oscillation"] == pytest.approx(8.2)
        assert row["avg_vertical_ratio"] == pytest.approx(6.1)
        assert row["avg_stride_length"] == pytest.approx(130.0)
        # cycling power fields present but null
        assert row["avg_power_w"] is None
        assert row["norm_power_w"] is None

    def test_lap_swimming_returns_per_pool_length_rows(self) -> None:
        from garmin_cli.serializers import serialize_activity_laps
        activity = {"activityType": {"typeKey": "lap_swimming"}}
        typed_splits = {
            "lengthDTOs": [
                {"duration": 25.0, "distance": 25.0, "swolf": 38, "swimStroke": "FREESTYLE",
                 "strokes": 14, "averageSwimCadenceInStrokesPerMinute": 30.0},
                {"duration": 26.0, "distance": 25.0, "swolf": 39, "swimStroke": "FREESTYLE",
                 "strokes": 15, "averageSwimCadenceInStrokesPerMinute": 31.0},
                {"duration": 28.0, "distance": 25.0, "swolf": 40, "swimStroke": "BACKSTROKE",
                 "strokes": 16, "averageSwimCadenceInStrokesPerMinute": 33.0},
            ],
        }
        rows = serialize_activity_laps(activity, typed_splits)
        assert len(rows) == 3
        assert rows[0]["lap_index"] == 1
        assert rows[0]["swolf"] == 38
        assert rows[0]["stroke_type"] == "FREESTYLE"
        assert rows[0]["strokes"] == 14
        assert rows[0]["avg_stroke_rate"] == 30.0
        assert rows[2]["stroke_type"] == "BACKSTROKE"

    def test_open_water_swim_uses_lap_dtos_not_length_dtos(self) -> None:
        from garmin_cli.serializers import serialize_activity_laps
        activity = {"activityType": {"typeKey": "open_water_swimming"}}
        splits = {
            "lapDTOs": [
                {"duration": 600.0, "distance": 1000.0, "averageHR": 140},
            ],
        }
        rows = serialize_activity_laps(activity, splits)
        assert len(rows) == 1
        assert rows[0]["distance_km"] == pytest.approx(1.0)
        assert rows[0]["avg_hr"] == 140
        # OWS uses run/bike shape (no swolf/strokes columns)
        assert "swolf" not in rows[0]

    def test_empty_payload_returns_empty_list(self) -> None:
        from garmin_cli.serializers import serialize_activity_laps
        assert serialize_activity_laps({"activityType": {"typeKey": "cycling"}}, {}) == []
        assert serialize_activity_laps({}, None) == []
        assert serialize_activity_laps({}, {"lapDTOs": []}) == []

    def test_missing_power_fields_are_null(self) -> None:
        from garmin_cli.serializers import serialize_activity_laps
        activity = {"activityType": {"typeKey": "cycling"}}
        splits = {"lapDTOs": [{"duration": 600.0, "distance": 5000.0, "averageHR": 145}]}
        row = serialize_activity_laps(activity, splits)[0]
        assert row["avg_power_w"] is None
        assert row["max_power_w"] is None
        assert row["norm_power_w"] is None
        # base fields populated
        assert row["avg_hr"] == 145

    def test_unknown_sport_falls_through_to_lap_dtos(self) -> None:
        from garmin_cli.serializers import serialize_activity_laps
        activity = {"activityType": {"typeKey": "weightlifting"}}
        splits = {"lapDTOs": [{"duration": 60.0, "distance": 0.0, "averageHR": 130}]}
        rows = serialize_activity_laps(activity, splits)
        assert len(rows) == 1
        assert rows[0]["avg_hr"] == 130


# ---------------------------------------------------------------------------
# Activity HR zones serializer
# ---------------------------------------------------------------------------


class TestSerializeActivityHrZones:

    def test_returns_one_row_per_zone(self) -> None:
        from garmin_cli.serializers import serialize_activity_hr_zones
        zones = [
            {"zoneNumber": 1, "zoneLowBoundary": 90, "zoneHighBoundary": 109, "secsInZone": 600},
            {"zoneNumber": 2, "zoneLowBoundary": 110, "zoneHighBoundary": 129, "secsInZone": 1200},
            {"zoneNumber": 3, "zoneLowBoundary": 130, "zoneHighBoundary": 149, "secsInZone": 1800},
            {"zoneNumber": 4, "zoneLowBoundary": 150, "zoneHighBoundary": 169, "secsInZone": 900},
            {"zoneNumber": 5, "zoneLowBoundary": 170, "zoneHighBoundary": 200, "secsInZone": 300},
        ]
        rows = serialize_activity_hr_zones(zones)
        assert len(rows) == 5
        assert rows[0]["zone"] == 1
        assert rows[0]["zone_low_bpm"] == 90
        assert rows[0]["zone_high_bpm"] == 109
        assert rows[0]["minutes_in_zone"] == pytest.approx(10.0)
        assert rows[0]["seconds_in_zone"] == 600

    def test_sorts_by_zone_number(self) -> None:
        from garmin_cli.serializers import serialize_activity_hr_zones
        zones = [
            {"zoneNumber": 3, "secsInZone": 900},
            {"zoneNumber": 1, "secsInZone": 300},
            {"zoneNumber": 2, "secsInZone": 600},
        ]
        rows = serialize_activity_hr_zones(zones)
        assert [r["zone"] for r in rows] == [1, 2, 3]

    def test_empty_returns_empty(self) -> None:
        from garmin_cli.serializers import serialize_activity_hr_zones
        assert serialize_activity_hr_zones([]) == []
        assert serialize_activity_hr_zones(None) == []

    def test_zero_seconds_emits_row_with_zero_minutes(self) -> None:
        from garmin_cli.serializers import serialize_activity_hr_zones
        rows = serialize_activity_hr_zones([{"zoneNumber": 5, "secsInZone": 0}])
        assert len(rows) == 1
        assert rows[0]["minutes_in_zone"] == 0.0

    def test_missing_boundaries_yield_none(self) -> None:
        from garmin_cli.serializers import serialize_activity_hr_zones
        rows = serialize_activity_hr_zones([{"zoneNumber": 1, "secsInZone": 60}])
        assert rows[0]["zone_low_bpm"] is None
        assert rows[0]["zone_high_bpm"] is None
        assert rows[0]["minutes_in_zone"] == pytest.approx(1.0)

    def test_columns_lockstep_with_row_keys(self) -> None:
        """Guard against COLUMNS_ACTIVITY_HR_ZONES drifting from the row shape
        (regression: seconds_in_zone was emitted but missing from the column
        tuple, so table/CSV output silently dropped it)."""
        from garmin_cli.serializers import (
            COLUMNS_ACTIVITY_HR_ZONES,
            serialize_activity_hr_zones,
        )
        rows = serialize_activity_hr_zones(
            [{"zoneNumber": 1, "zoneLowBoundary": 90, "zoneHighBoundary": 109, "secsInZone": 600}]
        )
        assert tuple(rows[0].keys()) == COLUMNS_ACTIVITY_HR_ZONES


# ---------------------------------------------------------------------------
# Metrics descriptors (U12)
# ---------------------------------------------------------------------------


class TestSerializeCapabilityManifest:
    """U11: capability manifest covers full registry union with two reasons."""

    def test_cycling_with_power_omits_power_from_manifest(self) -> None:
        from garmin_cli.serializers import (
            MANIFEST_REASON_ABSENT,
            MANIFEST_REASON_NOT_APPLICABLE,
            serialize_activity_detail,
            serialize_capability_manifest,
        )
        raw = {
            "activityId": 1, "activityType": {"typeKey": "cycling"},
            "averagePower": 220.0, "normPower": 240.0, "maxPower": 600.0,
            "trainingStressScore": 95.0, "intensityFactor": 0.88,
        }
        projected = serialize_activity_detail(raw)[0]
        manifest = serialize_capability_manifest(raw, projected)
        fields = {entry["field"]: entry["reason"] for entry in manifest}
        # cycling values present → not in manifest
        for key in ("avg_power_w", "norm_power_w", "tss", "intensity_factor"):
            assert key not in fields
        # running and swim metrics tagged not_applicable_to_sport
        for key in ("avg_ground_contact_time", "avg_stride_length", "swolf", "total_strokes"):
            assert fields.get(key) == MANIFEST_REASON_NOT_APPLICABLE

    def test_cycling_without_ftp_marks_tss_absent(self) -> None:
        from garmin_cli.serializers import (
            MANIFEST_REASON_ABSENT,
            serialize_activity_detail,
            serialize_capability_manifest,
        )
        raw = {
            "activityId": 1, "activityType": {"typeKey": "cycling"},
            "averagePower": 220.0,  # NP, IF, TSS unset (no FTP)
        }
        projected = serialize_activity_detail(raw)[0]
        manifest = serialize_capability_manifest(raw, projected)
        fields = {entry["field"]: entry["reason"] for entry in manifest}
        # NP, IF, TSS are cycling-applicable but absent
        assert fields.get("norm_power_w") == MANIFEST_REASON_ABSENT
        assert fields.get("tss") == MANIFEST_REASON_ABSENT
        assert fields.get("intensity_factor") == MANIFEST_REASON_ABSENT

    def test_lap_swim_marks_run_and_bike_metrics_not_applicable(self) -> None:
        from garmin_cli.serializers import (
            MANIFEST_REASON_NOT_APPLICABLE,
            serialize_activity_detail,
            serialize_capability_manifest,
        )
        raw = {
            "activityId": 1, "activityType": {"typeKey": "lap_swimming"},
            "avgSwolf": 38, "strokes": 720,
        }
        projected = serialize_activity_detail(raw)[0]
        manifest = serialize_capability_manifest(raw, projected)
        fields = {entry["field"]: entry["reason"] for entry in manifest}
        for key in ("avg_power_w", "norm_power_w", "tss", "intensity_factor",
                    "avg_cadence_rpm", "avg_ground_contact_time",
                    "avg_vertical_oscillation", "avg_stride_length",
                    "avg_cadence_spm"):
            assert fields.get(key) == MANIFEST_REASON_NOT_APPLICABLE

    def test_running_without_hrm_pro_marks_dynamics_absent(self) -> None:
        from garmin_cli.serializers import (
            MANIFEST_REASON_ABSENT,
            serialize_activity_detail,
            serialize_capability_manifest,
        )
        raw = {
            "activityId": 1, "activityType": {"typeKey": "running"},
            "averageRunningCadenceInStepsPerMinute": 175,
            # GCT/VO/VR/stride absent
        }
        projected = serialize_activity_detail(raw)[0]
        manifest = serialize_capability_manifest(raw, projected)
        fields = {entry["field"]: entry["reason"] for entry in manifest}
        assert fields.get("avg_ground_contact_time") == MANIFEST_REASON_ABSENT
        assert fields.get("avg_vertical_oscillation") == MANIFEST_REASON_ABSENT
        assert fields.get("avg_stride_length") == MANIFEST_REASON_ABSENT

    def test_universal_entry_only_emits_absent_never_not_applicable(self) -> None:
        from garmin_cli.serializers import (
            MANIFEST_REASON_NOT_APPLICABLE,
            serialize_activity_detail,
            serialize_capability_manifest,
        )
        # max_hr is universal (sports=None); for any sport it should never be
        # tagged not_applicable. Test for cycling, running, swim.
        for type_key in ("cycling", "running", "lap_swimming", "open_water_swimming"):
            raw = {"activityId": 1, "activityType": {"typeKey": type_key}, "maxHR": 180}
            projected = serialize_activity_detail(raw)[0]
            manifest = serialize_capability_manifest(raw, projected)
            for entry in manifest:
                if entry["field"] == "max_hr":
                    assert entry["reason"] != MANIFEST_REASON_NOT_APPLICABLE

    def test_empty_when_all_applicable_and_present(self) -> None:
        from garmin_cli.metrics.registry import REGISTRY
        from garmin_cli.serializers import serialize_capability_manifest
        # Build a "perfect cycling" payload that populates every cycling-applicable
        # metric so manifest should only contain not_applicable_to_sport entries
        # for non-cycling fields.
        raw = {
            "activityId": 1, "activityType": {"typeKey": "cycling"},
            "averageHR": 145, "maxHR": 180, "calories": 800,
            "elevationGain": 200.0, "elevationLoss": 200.0,
            "averageSpeed": 8.0, "maxSpeed": 15.0,
            "averageBikingCadenceInRevPerMinute": 85.0,
            "averagePower": 220, "maxPower": 600, "normPower": 235,
            "trainingStressScore": 90, "intensityFactor": 0.88,
            "aerobicTrainingEffect": 3.5, "anaerobicTrainingEffect": 1.2,
            "vO2MaxValue": 55.0, "recoveryTime": 1440,
            "startTimeLocal": "2026-04-01", "activityName": "Ride",
            "distance": 50000.0, "duration": 5400.0,
        }
        from garmin_cli.serializers import serialize_activity_detail
        projected = serialize_activity_detail(raw)[0]
        manifest = serialize_capability_manifest(raw, projected)
        # cycling-specific present-and-populated keys do not appear
        for key in ("avg_power_w", "norm_power_w", "tss", "intensity_factor",
                    "avg_cadence_rpm", "aerobic_training_effect", "vo2max"):
            assert all(e["field"] != key for e in manifest)

    def test_leg_index_set_when_provided(self) -> None:
        from garmin_cli.serializers import serialize_capability_manifest
        raw = {"activityId": 1, "activityType": {"typeKey": "running"}}
        manifest = serialize_capability_manifest(raw, leg_index=2)
        assert manifest, "expected non-empty manifest for running activity"
        for entry in manifest:
            assert entry["leg_index"] == 2

    def test_leg_index_none_by_default(self) -> None:
        from garmin_cli.serializers import serialize_capability_manifest
        raw = {"activityId": 1, "activityType": {"typeKey": "running"}}
        manifest = serialize_capability_manifest(raw)
        for entry in manifest:
            assert entry["leg_index"] is None

    def test_unknown_sport_marks_all_sport_specific_not_applicable(self) -> None:
        from garmin_cli.serializers import (
            MANIFEST_REASON_NOT_APPLICABLE,
            serialize_capability_manifest,
        )
        raw = {"activityId": 1, "activityType": {"typeKey": "weightlifting"}}
        manifest = serialize_capability_manifest(raw)
        # every sport-specific metric (sports != None) should be tagged
        sport_specific = [e for e in manifest if e["reason"] == MANIFEST_REASON_NOT_APPLICABLE]
        assert len(sport_specific) >= 5  # at least running + cycling + swim metrics

    def test_manifest_summary_counts(self) -> None:
        from garmin_cli.serializers import (
            MANIFEST_REASON_ABSENT,
            MANIFEST_REASON_NOT_APPLICABLE,
            manifest_summary_counts,
        )
        manifest = [
            {"field": "a", "reason": MANIFEST_REASON_NOT_APPLICABLE, "leg_index": None},
            {"field": "b", "reason": MANIFEST_REASON_NOT_APPLICABLE, "leg_index": None},
            {"field": "c", "reason": MANIFEST_REASON_ABSENT, "leg_index": None},
        ]
        not_app, absent = manifest_summary_counts(manifest)
        assert not_app == 2
        assert absent == 1


class TestSerializeMetricsDescriptors:

    def test_returns_one_row_per_descriptor(self) -> None:
        from garmin_cli.serializers import serialize_metrics_descriptors
        details = {
            "metricDescriptors": [
                {"key": "directHeartRate", "unit": {"key": "bpm"}, "metricsIndex": 0},
                {"key": "directPower", "unit": {"key": "W"}, "metricsIndex": 1},
                {"key": "directSpeed", "unit": {"key": "mps"}, "metricsIndex": 2},
            ],
        }
        rows = serialize_metrics_descriptors(details)
        assert len(rows) == 3
        assert rows[0] == {"key": "directHeartRate", "unit": "bpm", "metricsIndex": 0}
        assert rows[1] == {"key": "directPower", "unit": "W", "metricsIndex": 1}

    def test_descriptor_with_string_unit(self) -> None:
        from garmin_cli.serializers import serialize_metrics_descriptors
        details = {"metricDescriptors": [{"key": "x", "unit": "raw", "metricsIndex": 0}]}
        rows = serialize_metrics_descriptors(details)
        assert rows[0]["unit"] == "raw"

    def test_missing_unit_emits_none(self) -> None:
        from garmin_cli.serializers import serialize_metrics_descriptors
        details = {"metricDescriptors": [{"key": "x", "metricsIndex": 7}]}
        rows = serialize_metrics_descriptors(details)
        assert rows[0]["unit"] is None
        assert rows[0]["metricsIndex"] == 7

    def test_empty_returns_empty(self) -> None:
        from garmin_cli.serializers import serialize_metrics_descriptors
        assert serialize_metrics_descriptors({}) == []
        assert serialize_metrics_descriptors({"metricDescriptors": []}) == []
        assert serialize_metrics_descriptors(None) == []
