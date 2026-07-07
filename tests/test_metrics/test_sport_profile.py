"""Tests for sport profiles."""
from __future__ import annotations

import pytest

from garmin_cli.metrics import REGISTRY
from garmin_cli.metrics.sport_profile import (
    CYCLING_PROFILE,
    DEFAULT_PROFILE,
    LAP_SWIM_PROFILE,
    MULTI_SPORT_PROFILE,
    OPEN_WATER_SWIM_PROFILE,
    PROFILES,
    RUNNING_PROFILE,
    UNION_COLUMNS,
    SportProfile,
    columns_for_sport,
    profile_for,
)


class TestProfileFor:

    def test_running_returns_running_profile(self) -> None:
        profile = profile_for("running")
        assert profile is RUNNING_PROFILE
        assert "avg_ground_contact_time" in profile.standard_metrics

    def test_cycling_returns_cycling_profile(self) -> None:
        profile = profile_for("cycling")
        assert profile is CYCLING_PROFILE
        assert "norm_power_w" in profile.standard_metrics

    def test_lap_swimming_returns_swim_profile(self) -> None:
        profile = profile_for("lap_swimming")
        assert profile is LAP_SWIM_PROFILE
        assert "swolf" in profile.standard_metrics

    def test_trail_running_aliases_to_running(self) -> None:
        assert profile_for("trail_running") is RUNNING_PROFILE

    def test_treadmill_running_aliases_to_running(self) -> None:
        assert profile_for("treadmill_running") is RUNNING_PROFILE

    def test_indoor_cycling_aliases_to_cycling(self) -> None:
        assert profile_for("indoor_cycling") is CYCLING_PROFILE

    def test_road_biking_aliases_to_cycling(self) -> None:
        assert profile_for("road_biking") is CYCLING_PROFILE

    def test_open_water_swimming_returns_ows_profile(self) -> None:
        profile = profile_for("open_water_swimming")
        assert profile is OPEN_WATER_SWIM_PROFILE
        assert "swolf" not in profile.standard_metrics
        assert "distance_per_stroke" not in profile.standard_metrics

    def test_multi_sport_returns_multi_sport_profile(self) -> None:
        assert profile_for("multi_sport") is MULTI_SPORT_PROFILE
        assert profile_for("multisport") is MULTI_SPORT_PROFILE

    def test_unknown_sport_returns_default_profile(self) -> None:
        assert profile_for("unknown_sport") is DEFAULT_PROFILE
        assert profile_for("walking") is DEFAULT_PROFILE

    def test_none_sport_returns_default_profile(self) -> None:
        assert profile_for(None) is DEFAULT_PROFILE


class TestProfileComposition:

    def test_every_profile_starts_with_base_summary(self) -> None:
        base = ("id", "date", "name", "type", "distance_km", "duration_min", "avg_hr")
        for profile in PROFILES + (DEFAULT_PROFILE,):
            assert profile.summary_metrics == base

    def test_running_excludes_cycling_power_keys(self) -> None:
        for key in ("avg_power_w", "max_power_w", "norm_power_w", "tss", "intensity_factor"):
            assert key not in RUNNING_PROFILE.standard_metrics
            assert key not in RUNNING_PROFILE.detail_metrics()

    def test_cycling_excludes_running_dynamics_keys(self) -> None:
        for key in (
            "avg_cadence_spm",
            "avg_ground_contact_time",
            "avg_vertical_oscillation",
            "avg_vertical_ratio",
            "avg_stride_length",
        ):
            assert key not in CYCLING_PROFILE.standard_metrics

    def test_lap_swim_excludes_run_and_bike_keys(self) -> None:
        for key in (
            "avg_cadence_spm",
            "avg_cadence_rpm",
            "avg_power_w",
            "norm_power_w",
            "avg_ground_contact_time",
            "vo2max",
            "recovery_time_h",
        ):
            assert key not in LAP_SWIM_PROFILE.standard_metrics

    def test_training_effect_renders_for_every_profile(self) -> None:
        # Garmin emits training effect for swims too (verified live
        # 2026-07-07), so the keys are universal in the registry and must
        # appear in every profile's table columns.
        for profile in PROFILES + (DEFAULT_PROFILE,):
            assert "aerobic_training_effect" in profile.standard_metrics
            assert "anaerobic_training_effect" in profile.standard_metrics

    def test_detail_metrics_concatenates_summary_then_standard(self) -> None:
        for profile in PROFILES + (DEFAULT_PROFILE,):
            combined = profile.detail_metrics()
            assert combined == profile.summary_metrics + profile.standard_metrics


class TestRegistryCoverage:

    @pytest.mark.parametrize("profile", PROFILES + (DEFAULT_PROFILE,))
    def test_every_profile_key_resolves_in_registry(self, profile: SportProfile) -> None:
        for key in profile.detail_metrics():
            assert key in REGISTRY, f"{profile.type_keys}: missing registry entry for {key!r}"

    def test_every_union_column_resolves_in_registry(self) -> None:
        for key in UNION_COLUMNS:
            assert key in REGISTRY


class TestUnionColumns:

    def test_union_columns_starts_with_legacy_order(self) -> None:
        legacy_prefix = (
            "id", "date", "name", "type", "distance_km", "duration_min", "avg_hr",
            "max_hr", "calories", "elevation_gain_m", "elevation_loss_m",
            "avg_speed_kmh", "max_speed_kmh",
            "avg_cadence_spm", "avg_cadence_rpm",
            "avg_power_w", "max_power_w", "norm_power_w",
            "tss", "intensity_factor",
        )
        assert UNION_COLUMNS[: len(legacy_prefix)] == legacy_prefix

    def test_running_dynamics_appended_after_legacy(self) -> None:
        for key in ("avg_ground_contact_time", "avg_vertical_oscillation",
                    "avg_vertical_ratio", "avg_stride_length"):
            assert UNION_COLUMNS.index(key) > UNION_COLUMNS.index("intensity_factor")

    def test_swim_appended_after_running_dynamics(self) -> None:
        assert UNION_COLUMNS.index("swolf") > UNION_COLUMNS.index("avg_stride_length")
        assert UNION_COLUMNS.index("total_strokes") > UNION_COLUMNS.index("swolf")

    def test_union_columns_no_duplicates(self) -> None:
        assert len(UNION_COLUMNS) == len(set(UNION_COLUMNS))


class TestColumnsForSport:

    def test_cycling_columns_omit_running_dynamics(self) -> None:
        cols = columns_for_sport("cycling")
        for key in ("avg_ground_contact_time", "avg_stride_length"):
            assert key not in cols

    def test_running_columns_omit_cycling_power(self) -> None:
        cols = columns_for_sport("running")
        for key in ("avg_power_w", "norm_power_w", "tss"):
            assert key not in cols

    def test_lap_swim_columns_include_swim_metrics(self) -> None:
        cols = columns_for_sport("lap_swimming")
        for key in ("swolf", "total_strokes", "avg_stroke_rate"):
            assert key in cols

    def test_unknown_sport_columns_default_to_universal(self) -> None:
        cols = columns_for_sport("walking")
        assert "max_hr" in cols
        assert "avg_speed_kmh" in cols
        assert "norm_power_w" not in cols
        assert "swolf" not in cols
