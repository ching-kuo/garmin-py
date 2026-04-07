"""Tests for garmin_cli.endpoints.activities — list_activities, get_activity, get_activity_weather."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.activities import (
    get_activity,
    get_activity_weather,
    list_activities,
)
from garmin_cli.exceptions import GarminCliError
from tests.helpers import make_http_error as _http_error


# ---------------------------------------------------------------------------
# list_activities
# ---------------------------------------------------------------------------

class TestListActivities:

    def test_returns_list(self, mocker: Any, sample_activities_list_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_activities_list_raw
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = list_activities(limit=10, start=0, activity_type=None, search=None)
        assert isinstance(result, list)

    def test_empty_result_returns_empty_list(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = []
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = list_activities(limit=10, start=0, activity_type=None, search=None)
        assert result == []

    def test_limit_zero_raises_value_error(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises((ValueError, GarminCliError)):
            list_activities(limit=0, start=0, activity_type=None, search=None)

    def test_limit_negative_raises_value_error(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises((ValueError, GarminCliError)):
            list_activities(limit=-1, start=0, activity_type=None, search=None)

    def test_http_404_raises_not_found_error_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            list_activities(limit=10, start=0, activity_type=None, search=None)
        assert exc_info.value.error_code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# get_activity
# ---------------------------------------------------------------------------

class TestGetActivity:

    def test_returns_dict(self, mocker: Any, sample_activity_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_activity_raw
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = get_activity(12345678)
        assert result is not None

    def test_http_404_raises_not_found_error_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_activity(99999999)
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_string_activity_id_handled(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        get_activity("12345678")
        call_str = str(mock_garth.connectapi.call_args)
        assert "12345678" in call_str


# ---------------------------------------------------------------------------
# get_activity_weather
# ---------------------------------------------------------------------------

class TestGetActivityWeather:

    def test_returns_weather_data(self, mocker: Any, sample_activity_weather_raw: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = sample_activity_weather_raw
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = get_activity_weather(12345678)
        assert result is not None

    def test_http_404_raises_not_found_error_code(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_activity_weather(99999999)
        assert exc_info.value.error_code == "NOT_FOUND"
