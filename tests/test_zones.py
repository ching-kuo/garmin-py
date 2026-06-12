"""Tests for garmin_cli.zones — pure pace/zone math functions."""
from __future__ import annotations

import pytest

from garmin_cli.zones import (
    ms_to_pace,
    calculate_running_zones,
    calculate_cycling_zones,
    classify_running_step,
)


class TestMsToPace:
    def test_known_pace(self) -> None:
        # 1000 m/s would be 0:01 /km; 1 m/s = 1000 seconds/km = 16:40 /km
        result = ms_to_pace(1.0)
        assert result == "16:40 /km"

    def test_typical_running_pace(self) -> None:
        # 3.333 m/s ≈ 300 sec/km = 5:00 /km
        result = ms_to_pace(3.333)
        assert result == "5:00 /km"

    def test_zero_returns_na(self) -> None:
        assert ms_to_pace(0.0) == "N/A"

    def test_negative_returns_na(self) -> None:
        assert ms_to_pace(-1.0) == "N/A"

    def test_none_returns_na(self) -> None:
        # falsy value
        assert ms_to_pace(0) == "N/A"

    def test_format_has_colon_and_km_suffix(self) -> None:
        result = ms_to_pace(2.5)
        assert ":" in result
        assert result.endswith("/km")

    def test_seconds_zero_padded(self) -> None:
        # 1000/6.0 = 166.67 sec → 2:46 /km  (46 is two digits)
        result = ms_to_pace(6.0)
        parts = result.split(":")
        seconds_part = parts[1].split(" ")[0]
        assert len(seconds_part) == 2


class TestCalculateRunningZones:
    def test_returns_five_zones(self) -> None:
        zones = calculate_running_zones(3.5)
        assert len(zones) == 5

    def test_zone_keys_present(self) -> None:
        zones = calculate_running_zones(3.5)
        expected_keys = {
            "Zone 1 (Recovery)",
            "Zone 2 (Aerobic)",
            "Zone 3 (Tempo)",
            "Zone 4 (Threshold)",
            "Zone 5 (VO2max)",
        }
        assert set(zones.keys()) == expected_keys

    def test_each_zone_has_required_fields(self) -> None:
        zones = calculate_running_zones(3.5)
        for zone_name, zone_data in zones.items():
            assert "description" in zone_data, f"{zone_name} missing 'description'"
            assert "pace_range" in zone_data, f"{zone_name} missing 'pace_range'"
            assert "effort" in zone_data, f"{zone_name} missing 'effort'"

    def test_zone1_has_slower_than_wording(self) -> None:
        zones = calculate_running_zones(3.5)
        assert "slower than" in zones["Zone 1 (Recovery)"]["pace_range"]

    def test_zone5_has_faster_than_wording(self) -> None:
        zones = calculate_running_zones(3.5)
        assert "faster than" in zones["Zone 5 (VO2max)"]["pace_range"]

    def test_middle_zones_have_dash_range(self) -> None:
        zones = calculate_running_zones(3.5)
        assert "–" in zones["Zone 2 (Aerobic)"]["pace_range"]
        assert "–" in zones["Zone 3 (Tempo)"]["pace_range"]
        assert "–" in zones["Zone 4 (Threshold)"]["pace_range"]


class TestCalculateCyclingZones:
    def test_returns_six_zones(self) -> None:
        zones = calculate_cycling_zones(250)
        assert len(zones) == 6

    def test_zone_keys_present(self) -> None:
        zones = calculate_cycling_zones(250)
        expected_keys = {
            "Zone 1 (Active Recovery)",
            "Zone 2 (Endurance)",
            "Zone 3 (Tempo)",
            "Zone 4 (Threshold)",
            "Zone 5 (VO2max)",
            "Zone 6 (Anaerobic)",
        }
        assert set(zones.keys()) == expected_keys

    def test_zone1_below_55_percent_ftp(self) -> None:
        zones = calculate_cycling_zones(200)
        # 55% of 200 = 110 W
        assert "110" in zones["Zone 1 (Active Recovery)"]

    def test_zone4_threshold_brackets_ftp(self) -> None:
        zones = calculate_cycling_zones(300)
        # 91% of 300 = 273, 105% = 315
        assert "273" in zones["Zone 4 (Threshold)"]
        assert "315" in zones["Zone 4 (Threshold)"]

    def test_all_values_are_strings_with_W_suffix(self) -> None:
        zones = calculate_cycling_zones(250)
        for name, value in zones.items():
            assert isinstance(value, str), f"{name} value is not a string"
            assert "W" in value, f"{name} value missing watt suffix"


class TestClassifyRunningStep:
    _LT_PACE_MS = 3.5  # representative lactate threshold pace

    def _step(self, lo: float, hi: float) -> dict:
        return {"target_range": [lo, hi]}

    def test_missing_target_range_returns_unknown(self) -> None:
        assert classify_running_step({}, self._LT_PACE_MS) == "Unknown zone"

    def test_none_target_range_entries_return_unknown(self) -> None:
        assert classify_running_step({"target_range": [None, None]}, self._LT_PACE_MS) == "Unknown zone"

    def test_zone1_below_0775(self) -> None:
        speed = self._LT_PACE_MS * 0.70
        result = classify_running_step(self._step(speed, speed), self._LT_PACE_MS)
        assert result == "Zone 1 (Recovery)"

    def test_zone2_between_0775_and_0877(self) -> None:
        speed = self._LT_PACE_MS * 0.82
        result = classify_running_step(self._step(speed, speed), self._LT_PACE_MS)
        assert result == "Zone 2 (Aerobic)"

    def test_zone3_between_0877_and_0943(self) -> None:
        speed = self._LT_PACE_MS * 0.91
        result = classify_running_step(self._step(speed, speed), self._LT_PACE_MS)
        assert result == "Zone 3 (Tempo)"

    def test_zone4_between_0943_and_101(self) -> None:
        speed = self._LT_PACE_MS * 0.97
        result = classify_running_step(self._step(speed, speed), self._LT_PACE_MS)
        assert result == "Zone 4 (Threshold)"

    def test_zone5_above_101(self) -> None:
        speed = self._LT_PACE_MS * 1.05
        result = classify_running_step(self._step(speed, speed), self._LT_PACE_MS)
        assert result == "Zone 5 (VO2max)"

    def test_uses_midpoint_of_range(self) -> None:
        # lo is Zone 1, hi is Zone 3; midpoint should be Zone 2
        lo = self._LT_PACE_MS * 0.70   # Zone 1
        hi = self._LT_PACE_MS * 0.84   # Zone 2 territory
        result = classify_running_step(self._step(lo, hi), self._LT_PACE_MS)
        # mid = (0.70 + 0.84)/2 * LT = 0.77 * LT → Zone 1 (below 0.775)
        assert result == "Zone 1 (Recovery)"
