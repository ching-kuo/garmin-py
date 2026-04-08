"""Tests for garmin_cli.endpoints.activities — list_activities, get_activity, get_activity_weather, multisport."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.activities import (
    get_activity,
    get_activity_splits,
    get_activity_weather,
    get_multisport_children,
    is_multisport_parent,
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

    def test_passes_start_date_param(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = []
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        list_activities(
            limit=10, start=0, activity_type=None, search=None,
            start_date=date(2026, 3, 1), end_date=None,
        )
        call_kwargs = mock_garth.connectapi.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        assert params["startDate"] == "2026-03-01"
        assert "endDate" not in params

    def test_passes_both_date_params(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = []
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        list_activities(
            limit=10, start=0, activity_type=None, search=None,
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 10),
        )
        call_kwargs = mock_garth.connectapi.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        assert params["startDate"] == "2026-03-01"
        assert params["endDate"] == "2026-03-10"

    def test_no_date_params_by_default(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = []
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        list_activities(limit=10, start=0, activity_type=None, search=None)
        call_kwargs = mock_garth.connectapi.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        assert "startDate" not in params
        assert "endDate" not in params


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


# ---------------------------------------------------------------------------
# get_activity_splits
# ---------------------------------------------------------------------------

class TestGetActivitySplits:

    def test_returns_splits_data(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {"lapDTOs": []}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = get_activity_splits(12345678)
        assert isinstance(result, dict)

    def test_returns_empty_dict_on_none(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = None
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = get_activity_splits(12345678)
        assert result == {}


# ---------------------------------------------------------------------------
# is_multisport_parent
# ---------------------------------------------------------------------------

class TestIsMultisportParent:

    def test_detects_top_level_flag(self) -> None:
        activity = {"isMultiSportParent": True, "activityType": {"typeKey": "running"}}
        assert is_multisport_parent(activity) is True

    def test_detects_metadata_flag(self) -> None:
        activity = {"metadataDTO": {"isMultiSportParent": True}, "activityType": {"typeKey": "running"}}
        assert is_multisport_parent(activity) is True

    def test_detects_multi_sport_type_key(self) -> None:
        activity = {"activityType": {"typeKey": "multi_sport"}}
        assert is_multisport_parent(activity) is True

    def test_detects_multisport_type_key(self) -> None:
        activity = {"activityType": {"typeKey": "multisport"}}
        assert is_multisport_parent(activity) is True

    def test_detects_child_ids_only(self) -> None:
        activity = {"childIds": [111, 222], "activityType": {"typeKey": "running"}}
        assert is_multisport_parent(activity) is True

    def test_detects_metadata_child_ids_only(self) -> None:
        activity = {"metadataDTO": {"childIds": [111, 222]}}
        assert is_multisport_parent(activity) is True

    def test_false_for_regular_activity(self) -> None:
        activity = {"activityType": {"typeKey": "running"}, "isMultiSportParent": False}
        assert is_multisport_parent(activity) is False

    def test_false_for_empty(self) -> None:
        assert is_multisport_parent({}) is False


# ---------------------------------------------------------------------------
# get_multisport_children
# ---------------------------------------------------------------------------

class TestGetMultisportChildren:

    def test_fetches_children_from_child_ids(
        self, mocker: Any, sample_multisport_parent_raw: Any, sample_multisport_children_raw: Any,
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = sample_multisport_children_raw
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        children = get_multisport_children(sample_multisport_parent_raw)
        assert len(children) == 3
        assert children[0]["activityName"] == "Swim"
        assert children[2]["activityName"] == "Run"

    def test_fetches_children_from_metadata_child_ids(self, mocker: Any) -> None:
        parent = {
            "metadataDTO": {"childIds": [111, 222]},
        }
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [
            {"activityId": 111, "activityName": "Swim"},
            {"activityId": 222, "activityName": "Bike"},
        ]
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        children = get_multisport_children(parent)
        assert len(children) == 2

    def test_returns_empty_for_no_children(self) -> None:
        parent = {"activityType": {"typeKey": "running"}}
        assert get_multisport_children(parent) == []

    def test_skips_failed_child_fetch(self, mocker: Any) -> None:
        parent = {"childIds": [111, 222]}
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [
            {"activityId": 111, "activityName": "Swim"},
            _http_error(404),
        ]
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        children = get_multisport_children(parent)
        assert len(children) == 1

    def test_reraises_auth_error(self, mocker: Any) -> None:
        parent = {"childIds": [111]}
        mock_garth = MagicMock()
        # 401 is not caught by _make_request as GarminCliError, so it
        # propagates as a raw Exception through get_multisport_children.
        mock_garth.connectapi.side_effect = _http_error(401)
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(Exception, match="401"):
            get_multisport_children(parent)

    def test_reraises_garmin_auth_error(self, mocker: Any) -> None:
        parent = {"childIds": [111]}
        mocker.patch(
            "garmin_cli.endpoints.activities.get_activity",
            side_effect=GarminCliError(error="Auth failed", error_code="AUTH_FAILED"),
        )

        with pytest.raises(GarminCliError) as exc_info:
            get_multisport_children(parent)
        assert exc_info.value.error_code == "AUTH_FAILED"

    def test_reraises_rate_limited_error(self, mocker: Any) -> None:
        parent = {"childIds": [111]}
        mocker.patch(
            "garmin_cli.endpoints.activities.get_activity",
            side_effect=GarminCliError(error="Rate limited", error_code="RATE_LIMITED"),
        )

        with pytest.raises(GarminCliError) as exc_info:
            get_multisport_children(parent)
        assert exc_info.value.error_code == "RATE_LIMITED"
