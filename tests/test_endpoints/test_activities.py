"""Tests for garmin_cli.endpoints.activities — list_activities, get_activity, get_activity_weather, multisport."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.activities import (
    delete_activity,
    download_activity,
    extension_for_format,
    get_activity,
    get_activity_details,
    get_activity_hr_in_timezones,
    get_activity_splits,
    get_activity_typed_splits,
    get_activity_weather,
    get_multisport_children,
    is_multisport_parent,
    list_activities,
    upload_activity,
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
# get_activity_typed_splits (U6) — typed backend-adapter method, not raw URL
# ---------------------------------------------------------------------------


class TestGetActivityTypedSplits:

    def test_invokes_typed_method_not_raw_url(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_typed_splits.return_value = {"lengthDTOs": []}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = get_activity_typed_splits("12345")

        # binding: the typed method is called, not connectapi/raw URL
        mock_garth.get_activity_typed_splits.assert_called_once_with(12345)
        mock_garth.connectapi.assert_not_called()
        assert result == {"lengthDTOs": []}

    def test_returns_response_dict_with_length_dtos(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_typed_splits.return_value = {
            "lengthDTOs": [{"swolf": 38, "strokes": 12}],
            "lapDTOs": [],
        }
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = get_activity_typed_splits(123)
        assert "lengthDTOs" in result
        assert result["lengthDTOs"][0]["swolf"] == 38

    def test_returns_empty_dict_when_backend_returns_none(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_typed_splits.return_value = None
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        assert get_activity_typed_splits(1) == {}

    def test_returns_empty_dict_for_empty_response(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_typed_splits.return_value = {}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        assert get_activity_typed_splits(1) == {}

    def test_negative_id_is_accepted(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_typed_splits.return_value = {}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        get_activity_typed_splits(-1)
        mock_garth.get_activity_typed_splits.assert_called_once_with(-1)

    @pytest.mark.parametrize("invalid", ["abc", "12.5", "not_a_number"])
    def test_non_numeric_id_raises_invalid_input(self, mocker: Any, invalid: str) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_activity_typed_splits(invalid)
        assert exc_info.value.error_code == "INVALID_INPUT"

    def test_http_404_raises_not_found(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_typed_splits.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_activity_typed_splits(99999999)
        assert exc_info.value.error_code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# get_activity_hr_in_timezones (U9) — typed backend-adapter method
# ---------------------------------------------------------------------------


class TestGetActivityHrInTimezones:

    def test_invokes_typed_method(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_hr_in_timezones.return_value = [
            {"zoneNumber": 1, "secsInZone": 600, "zoneLowBoundary": 100, "zoneHighBoundary": 120},
        ]
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = get_activity_hr_in_timezones(123)
        mock_garth.get_activity_hr_in_timezones.assert_called_once_with(123)
        mock_garth.connectapi.assert_not_called()
        assert isinstance(result, list)
        assert result[0]["zoneNumber"] == 1

    def test_returns_empty_list_when_none(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_hr_in_timezones.return_value = None
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        assert get_activity_hr_in_timezones(1) == []

    def test_returns_empty_list_for_unexpected_dict(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_hr_in_timezones.return_value = {}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        assert get_activity_hr_in_timezones(1) == []

    def test_unwraps_dict_with_time_in_zones_key(self, mocker: Any) -> None:
        """Some upstream releases wrap zones under a ``timeInZones`` key."""
        zones_list = [{"zoneNumber": 1, "secsInZone": 120}]
        mock_garth = MagicMock()
        mock_garth.get_activity_hr_in_timezones.return_value = {"timeInZones": zones_list}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = get_activity_hr_in_timezones(1)
        assert result == zones_list

    def test_unwraps_dict_with_zones_key(self, mocker: Any) -> None:
        zones_list = [{"zoneNumber": 1, "secsInZone": 60}]
        mock_garth = MagicMock()
        mock_garth.get_activity_hr_in_timezones.return_value = {"zones": zones_list}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = get_activity_hr_in_timezones(1)
        assert result == zones_list

    def test_negative_id_accepted(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_hr_in_timezones.return_value = []
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        get_activity_hr_in_timezones(-1)
        mock_garth.get_activity_hr_in_timezones.assert_called_once_with(-1)

    @pytest.mark.parametrize("invalid", ["abc", "12.5"])
    def test_non_numeric_id_raises_invalid_input(self, mocker: Any, invalid: str) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_activity_hr_in_timezones(invalid)
        assert exc_info.value.error_code == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# get_activity_details (U12) — typed backend-adapter method
# ---------------------------------------------------------------------------


class TestGetActivityDetails:

    def test_invokes_typed_method(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_details.return_value = {
            "metricDescriptors": [{"key": "directHeartRate", "unit": {"key": "bpm"}}],
        }
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = get_activity_details("123")
        mock_garth.get_activity_details.assert_called_once_with(123)
        mock_garth.connectapi.assert_not_called()
        assert "metricDescriptors" in result

    def test_returns_empty_dict_when_none(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_details.return_value = None
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        assert get_activity_details(1) == {}

    def test_negative_id_accepted(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_activity_details.return_value = {}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        get_activity_details(-1)
        mock_garth.get_activity_details.assert_called_once_with(-1)

    @pytest.mark.parametrize("invalid", ["abc", "12.5"])
    def test_non_numeric_id_raises_invalid_input(self, mocker: Any, invalid: str) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_activity_details(invalid)
        assert exc_info.value.error_code == "INVALID_INPUT"


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


# ---------------------------------------------------------------------------
# Activity lifecycle: download / upload / delete (typed backend methods)
# ---------------------------------------------------------------------------


class TestDownloadActivity:

    def test_returns_bytes_and_invokes_typed_method(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.download_activity.return_value = b"FITDATA"
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = download_activity("12345", "original")

        assert result == b"FITDATA"
        mock_garth.download_activity.assert_called_once()
        # numeric id is validated/coerced; format enum is passed through
        args, _ = mock_garth.download_activity.call_args
        assert args[0] == 12345

    def test_invalid_format_raises_invalid_input_without_api_call(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc:
            download_activity("12345", "pdf")

        assert exc.value.error_code == "INVALID_INPUT"
        mock_garth.download_activity.assert_not_called()

    def test_non_bytes_response_raises_server_error(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.download_activity.return_value = {"unexpected": "json"}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc:
            download_activity(1, "gpx")

        assert exc.value.error_code == "SERVER_ERROR"

    def test_bytearray_is_coerced_to_bytes(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.download_activity.return_value = bytearray(b"abc")
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = download_activity(7, "tcx")
        assert result == b"abc"
        assert isinstance(result, bytes)


class TestExtensionForFormat:

    def test_known_formats(self) -> None:
        assert extension_for_format("original") == ".zip"
        assert extension_for_format("tcx") == ".tcx"
        assert extension_for_format("gpx") == ".gpx"
        assert extension_for_format("kml") == ".kml"
        assert extension_for_format("csv") == ".csv"

    def test_case_insensitive(self) -> None:
        assert extension_for_format("GPX") == ".gpx"

    def test_unknown_format_falls_back_to_dotted_name(self) -> None:
        assert extension_for_format("xyz") == ".xyz"


class TestUploadActivity:

    def test_happy_path_invokes_typed_method(self, mocker: Any, tmp_path: Any) -> None:
        f = tmp_path / "ride.fit"
        f.write_bytes(b"FIT")
        mock_garth = MagicMock()
        mock_garth.upload_activity.return_value = {"detailedImportResult": {"successes": [{"internalId": 99}]}}
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        result = upload_activity(str(f))

        mock_garth.upload_activity.assert_called_once_with(str(f))
        assert result["detailedImportResult"]["successes"][0]["internalId"] == 99

    def test_missing_file_raises_invalid_input(self, mocker: Any, tmp_path: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc:
            upload_activity(str(tmp_path / "nope.fit"))

        assert exc.value.error_code == "INVALID_INPUT"
        mock_garth.upload_activity.assert_not_called()

    def test_directory_path_raises_invalid_input(self, mocker: Any, tmp_path: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc:
            upload_activity(str(tmp_path))

        assert exc.value.error_code == "INVALID_INPUT"

    def test_unsupported_extension_raises_invalid_input(self, mocker: Any, tmp_path: Any) -> None:
        f = tmp_path / "data.csv"
        f.write_text("x")
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc:
            upload_activity(str(f))

        assert exc.value.error_code == "INVALID_INPUT"
        mock_garth.upload_activity.assert_not_called()


class TestDeleteActivity:

    def test_invokes_typed_method_with_validated_id(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.delete_activity.return_value = None
        mocker.patch("garmin_cli.endpoints.activities.garth", mock_garth)

        delete_activity("12345")

        mock_garth.delete_activity.assert_called_once_with(12345)
