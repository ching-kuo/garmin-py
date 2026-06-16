"""Regression tests for the connector data-gap fixes.

Each test is grounded in the real ``/activity/{id}`` wire shape observed for a
road-cycling activity whose top-level ``activityType`` is null and whose sport
lives under ``activityTypeDTO`` (the condition that previously cascaded into
null ``type`` and bogus ``not_applicable_to_sport`` flags). Covers:

* sport-type fallback to ``activityTypeDTO`` (summary, detail, manifest),
* cadence mapped from ``averageBikeCadence`` (summary + per-lap),
* ``elapsed_time_min`` from ``elapsedDuration`` (total vs moving time),
* per-lap ``start_time_gmt`` passthrough + derived ``start_time_local``,
* weather remap from the real Garmin keys (``temp``/``relativeHumidity``/...).
"""
from __future__ import annotations

import pytest

from garmin_cli.endpoints.activities import activity_type_key, is_multisport_parent
from garmin_cli.serializers import (
    MANIFEST_REASON_NOT_APPLICABLE,
    serialize_activity_detail,
    serialize_activity_laps,
    serialize_activity_summary,
    serialize_activity_weather,
    serialize_capability_manifest,
)

# A road-cycling activity with the top-level activityType nulled (sport carried
# only by activityTypeDTO) and cadence/elapsed populated as Garmin emits them.
CYCLING_ACTIVITY: dict = {
    "activityId": 23229354391,
    "activityName": "Tsuchiura Ride",
    "activityType": None,
    "activityTypeDTO": {"typeId": 10, "typeKey": "road_biking"},
    "summaryDTO": {
        "startTimeGMT": "2026-06-12T23:53:55.0",
        "startTimeLocal": "2026-06-13T08:53:55.0",
        "distance": 125000.0,
        "duration": 13827.997,
        "movingDuration": 13802.033,
        "elapsedDuration": 16448.975,
        "averageHR": 140,
        "averagePower": 145,
        "averageBikeCadence": 86.0,
        "maxSpeed": 12.065,
        "trainingStressScore": 153.1,
        "intensityFactor": 0.632,
    },
}


class TestSportTypeFallback:
    def test_summary_type_from_activity_type_dto(self) -> None:
        row = serialize_activity_summary(CYCLING_ACTIVITY)[0]
        assert row["type"] == "road_biking"

    def test_detail_type_from_activity_type_dto(self) -> None:
        row = serialize_activity_detail(CYCLING_ACTIVITY)[0]
        assert row["type"] == "road_biking"

    def test_endpoint_helper_falls_back_to_dto(self) -> None:
        assert activity_type_key(CYCLING_ACTIVITY) == "road_biking"
        assert activity_type_key({"activityType": {"typeKey": "running"}}) == "running"
        assert activity_type_key({}) is None

    def test_multisport_parent_detected_via_dto(self) -> None:
        # Null top-level activityType, sport only under activityTypeDTO, and no
        # isMultiSportParent/childIds flags -> must still classify as a parent.
        activity = {"activityType": None, "activityTypeDTO": {"typeKey": "multi_sport"}}
        assert is_multisport_parent(activity) is True


class TestCapabilityManifestCascade:
    """A resolvable sport must not flag populated cycling metrics unavailable."""

    def test_cycling_metrics_not_flagged_not_applicable(self) -> None:
        projected = serialize_activity_detail(CYCLING_ACTIVITY)[0]
        manifest = serialize_capability_manifest(CYCLING_ACTIVITY, projected)
        not_applicable = {
            e["field"] for e in manifest
            if e["reason"] == MANIFEST_REASON_NOT_APPLICABLE
        }
        # Populated cycling metrics must be absent from the manifest entirely.
        for field in ("avg_power_w", "tss", "intensity_factor", "avg_cadence_rpm"):
            assert field not in not_applicable
        # Running-only metrics remain correctly flagged for a cycling activity.
        assert "avg_cadence_spm" in not_applicable

    def test_populated_cycling_values_survive(self) -> None:
        row = serialize_activity_detail(CYCLING_ACTIVITY)[0]
        assert row["avg_power_w"] == 145
        assert row["tss"] == 153.1
        assert row["intensity_factor"] == 0.632


class TestCadenceAndElapsed:
    def test_cadence_from_average_bike_cadence(self) -> None:
        row = serialize_activity_detail(CYCLING_ACTIVITY)[0]
        assert row["avg_cadence_rpm"] == 86.0

    def test_elapsed_and_moving_time_distinct(self) -> None:
        row = serialize_activity_detail(CYCLING_ACTIVITY)[0]
        # duration_min is moving time; elapsed_time_min is total wall-clock.
        assert row["duration_min"] == pytest.approx(230.47, abs=0.01)
        assert row["elapsed_time_min"] == pytest.approx(274.15, abs=0.01)
        assert row["elapsed_time_min"] > row["duration_min"]


class TestLapCadenceAndTimestamps:
    SPLITS: dict = {
        "lapDTOs": [
            {
                "startTimeGMT": "2026-06-12T23:53:55.0",
                "duration": 593.195,
                "distance": 5000.0,
                "averageHR": 145,
                "averagePower": 150,
                "averageBikeCadence": 87.0,
            },
            {
                "startTimeGMT": "2026-06-13T00:03:48.0",
                "duration": 600.0,
                "distance": 5100.0,
                "averageHR": 150,
                "averagePower": 155,
                "averageBikeCadence": 84.0,
            },
        ]
    }

    def test_lap_cadence_mapped(self) -> None:
        rows = serialize_activity_laps(CYCLING_ACTIVITY, self.SPLITS)
        assert rows[0]["avg_cadence_rpm"] == 87.0
        assert rows[1]["avg_cadence_rpm"] == 84.0

    def test_lap_start_time_gmt_passthrough(self) -> None:
        rows = serialize_activity_laps(CYCLING_ACTIVITY, self.SPLITS)
        assert rows[0]["start_time_gmt"] == "2026-06-12T23:53:55.0"

    def test_lap_start_time_local_derived(self) -> None:
        # Activity offset is +09:00 (Japan); GMT 23:53:55 -> local 08:53:55 next day.
        rows = serialize_activity_laps(CYCLING_ACTIVITY, self.SPLITS)
        assert rows[0]["start_time_local"] == "2026-06-13T08:53:55"
        assert rows[1]["start_time_local"] == "2026-06-13T09:03:48"

    def test_lap_local_truncates_subsecond(self) -> None:
        # A sub-second source component must not widen the derived local stamp
        # to microsecond formatting.
        splits = {"lapDTOs": [{"startTimeGMT": "2026-06-12T23:53:55.123", "duration": 60.0}]}
        rows = serialize_activity_laps(CYCLING_ACTIVITY, splits)
        assert rows[0]["start_time_local"] == "2026-06-13T08:53:55"

    def test_lap_local_none_when_offset_underivable(self) -> None:
        # No activity-level local stamp -> offset unknown -> local is None,
        # but the raw GMT stamp is still surfaced.
        activity = {"activityTypeDTO": {"typeKey": "road_biking"}}
        rows = serialize_activity_laps(activity, self.SPLITS)
        assert rows[0]["start_time_gmt"] == "2026-06-12T23:53:55.0"
        assert rows[0]["start_time_local"] is None


class TestWeatherRemap:
    RAW: dict = {
        "temp": 74,
        "apparentTemp": 74,
        "dewPoint": 66,
        "relativeHumidity": 72,
        "windDirection": 158,
        "windDirectionCompassPoint": "sse",
        "windSpeed": 2,
        "windGust": None,
        "weatherTypeDTO": {"desc": "Partly Cloudy"},
    }

    def test_maps_real_keys(self) -> None:
        row = serialize_activity_weather(self.RAW)[0]
        assert row["temperature"] == 74
        assert row["apparent_temp"] == 74
        assert row["dew_point"] == 66
        assert row["humidity"] == 72
        assert row["wind_speed"] == 2
        assert row["wind_direction"] == 158
        assert row["wind_direction_compass"] == "sse"
        assert row["condition"] == "Partly Cloudy"

    def test_condition_missing_weather_type_dto(self) -> None:
        row = serialize_activity_weather({"temp": 50})[0]
        assert row["temperature"] == 50
        assert row["condition"] is None

    def test_empty_payload_yields_no_rows(self) -> None:
        assert serialize_activity_weather({}) == []
        assert serialize_activity_weather(None) == []
