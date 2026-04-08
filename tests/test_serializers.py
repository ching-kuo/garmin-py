"""Tests for garmin_cli.serializers — all serialize_* functions and COLUMNS."""
from __future__ import annotations

from typing import Any

import pytest

from garmin_cli.serializers import (
    COLUMNS_ACTIVITY_SUMMARY,
    COLUMNS_CALENDAR_WORKOUT,
    COLUMNS_HRV,
    COLUMNS_MULTISPORT_CHILDREN,
    COLUMNS_SLEEP,
    COLUMNS_THRESHOLDS,
    COLUMNS_WEIGHT,
    serialize_activity_summary,
    serialize_calendar_workout,
    serialize_hrv,
    serialize_multisport_children,
    serialize_sleep,
    serialize_thresholds,
    serialize_weight,
)


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

    def test_contains_date_key(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert "date" in result[0]

    def test_date_value_correct(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert result[0]["date"] == "2026-03-11"

    def test_duration_hours_present(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert "duration_hours" in result[0]

    def test_duration_hours_correct(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        # 27000 seconds / 3600 = 7.5 hours
        assert result[0]["duration_hours"] == pytest.approx(7.5, rel=0.01)

    def test_deep_min_present(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert "deep_min" in result[0]

    def test_deep_min_correct(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        # 5400 seconds / 60 = 90 minutes
        assert result[0]["deep_min"] == pytest.approx(90, rel=0.01)

    def test_light_min_present(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert "light_min" in result[0]

    def test_rem_min_present(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert "rem_min" in result[0]

    def test_awake_min_present(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert "awake_min" in result[0]

    def test_score_present(self, sample_sleep_raw: Any) -> None:
        result = serialize_sleep(sample_sleep_raw)
        assert "score" in result[0]

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

    def test_columns_contains_required_fields(self) -> None:
        for col in ("date", "duration_hours", "deep_min", "light_min", "rem_min", "awake_min", "score"):
            assert col in COLUMNS_SLEEP



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

    def test_columns_contains_required_fields(self) -> None:
        for col in ("date", "weekly_avg", "last_night", "status"):
            assert col in COLUMNS_HRV


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

    def test_columns_contains_required_fields(self) -> None:
        for col in ("date", "weight_kg", "bmi", "body_fat_pct"):
            assert col in COLUMNS_WEIGHT



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

    def test_columns_contains_required_fields(self) -> None:
        for col in ("id", "date", "name", "type", "distance_km", "duration_min", "avg_hr"):
            assert col in COLUMNS_ACTIVITY_SUMMARY

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

    def test_columns_contains_required_fields(self) -> None:
        for col in ("id", "sport", "name", "distance_km", "duration_min", "avg_hr", "avg_pace", "calories"):
            assert col in COLUMNS_MULTISPORT_CHILDREN


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

    def test_columns_contains_required_fields(self) -> None:
        for col in ("date", "name", "type", "duration_min", "description"):
            assert col in COLUMNS_CALENDAR_WORKOUT



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

    def test_columns_contains_required_fields(self) -> None:
        for col in ("sport", "lt_hr_bpm", "lt_pace", "ftp_watts", "weight_kg"):
            assert col in COLUMNS_THRESHOLDS

