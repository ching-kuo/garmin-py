"""Tests for garmin_cli.fueling — fueling-workflow API helpers."""
from __future__ import annotations

import importlib
import pytest


class TestImportability:
    def test_garmin_cli_fueling_importable(self) -> None:
        fueling = importlib.import_module("garmin_cli.fueling")
        assert fueling is not None

    def test_garmin_cli_zones_importable(self) -> None:
        zones = importlib.import_module("garmin_cli.zones")
        assert zones is not None

    def test_old_garmin_package_gone(self) -> None:
        """The top-level 'garmin' shadow package must not be importable."""
        import sys
        sys.modules.pop("garmin", None)
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("garmin")

    def test_fueling_exposes_expected_functions(self) -> None:
        import garmin_cli.fueling as fueling
        for name in (
            "get_workout",
            "get_calendar",
            "get_lactate_threshold",
            "get_power_to_weight",
            "get_all_user_thresholds",
            "update_workout_description",
        ):
            assert callable(getattr(fueling, name, None)), (
                f"garmin_cli.fueling.{name} is missing or not callable"
            )


class TestGetCalendarValidation:
    """Unit tests for get_calendar input validation — no network needed."""

    def test_invalid_year_raises(self) -> None:
        from garmin_cli.fueling import get_calendar
        with pytest.raises(ValueError, match="Year must be"):
            get_calendar(year=1800, month=1)

    def test_invalid_month_raises(self) -> None:
        from garmin_cli.fueling import get_calendar
        with pytest.raises(ValueError, match="Month must be"):
            get_calendar(year=2024, month=13)

    def test_invalid_day_raises(self) -> None:
        from garmin_cli.fueling import get_calendar
        with pytest.raises(ValueError, match="Day must be"):
            get_calendar(year=2024, month=6, day=32)

    def test_valid_month_boundary_accepted(self) -> None:
        """Month=12 is valid — no ValueError raised (network call will fail, not ValueError)."""
        from garmin_cli.fueling import get_calendar
        with pytest.raises(Exception) as exc_info:
            get_calendar(year=2024, month=12)
        # Must NOT be a ValueError from our validation
        assert not isinstance(exc_info.value, ValueError)


class TestUpdateWorkoutDescriptionLogic:
    """Unit tests for update_workout_description truncation logic."""

    def _call(
        self,
        mocker,
        existing: str,
        fueling_text: str,
        max_length: int = 1024,
    ):
        connectapi_mock = mocker.patch("garmin_cli.fueling.garth.connectapi")
        from garmin_cli.fueling import update_workout_description
        update_workout_description(
            workout_id="12345",
            workout_data={"description": existing},
            fueling_text=fueling_text,
            max_length=max_length,
        )
        return connectapi_mock

    def test_appends_with_separator(self, mocker) -> None:
        mock = self._call(mocker, existing="Original.", fueling_text="Fuel plan.")
        assert mock.called
        _, kwargs = mock.call_args
        desc = kwargs.get("json", {}).get("description", "")
        assert "Original." in desc
        assert "Fuel plan." in desc
        assert "---" in desc

    def test_no_separator_when_no_existing(self, mocker) -> None:
        mock = self._call(mocker, existing="", fueling_text="Fuel plan.")
        _, kwargs = mock.call_args
        desc = kwargs.get("json", {}).get("description", "")
        assert desc == "Fuel plan."

    def test_truncates_fueling_text_when_over_limit(self, mocker) -> None:
        existing = "A" * 50
        fueling_text = "B" * 500
        mock = self._call(mocker, existing=existing, fueling_text=fueling_text, max_length=100)
        assert mock.called
        _, kwargs = mock.call_args
        desc = kwargs.get("json", {}).get("description", "")
        assert len(desc) <= 100
        assert desc.endswith("...")

    def test_skips_put_when_no_room(self, mocker) -> None:
        existing = "A" * 95
        fueling_text = "B" * 50
        mock = self._call(mocker, existing=existing, fueling_text=fueling_text, max_length=100)
        # Not enough room (< 20 chars available for fueling text), PUT should be skipped
        assert not mock.called

    def test_method_is_put(self, mocker) -> None:
        mock = self._call(mocker, existing="", fueling_text="Fuel.")
        _, kwargs = mock.call_args
        assert kwargs.get("method") == "PUT"

    def test_workout_id_in_endpoint(self, mocker) -> None:
        connectapi_mock = mocker.patch("garmin_cli.fueling.garth.connectapi")
        from garmin_cli.fueling import update_workout_description
        update_workout_description(
            workout_id="99999",
            workout_data={"description": ""},
            fueling_text="Fuel.",
        )
        url_arg = connectapi_mock.call_args[0][0]
        assert "99999" in url_arg
