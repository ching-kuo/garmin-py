"""Tests for extract_status_code and _make_write_request from garmin_cli.endpoints._base."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints._base import extract_status_code, _make_write_request
from garmin_cli.exceptions import GarminCliError
from tests.helpers import make_http_error as _http_error


# ---------------------------------------------------------------------------
# extract_status_code
# ---------------------------------------------------------------------------

class TestStatusCode:

    def test_returns_none_for_plain_exception(self) -> None:
        exc = Exception("plain error")
        assert extract_status_code(exc) is None

    def test_returnsextract_status_code_from_exc_response(self) -> None:
        exc = Exception("HTTP 401")
        exc.response = MagicMock(status_code=401)  # type: ignore[attr-defined]
        assert extract_status_code(exc) == 401

    def test_returnsextract_status_code_from_garth_http_error(self) -> None:
        # GarthHTTPError structure: exc.error is HTTPError, exc.error.response.status_code
        garth_exc = MagicMock()
        garth_exc.error = MagicMock()
        garth_exc.error.response = MagicMock(status_code=403)
        # Remove the direct response attribute so it falls through to .error.response
        del garth_exc.response
        assert extract_status_code(garth_exc) == 403

    def test_returns_none_when_response_has_noextract_status_code(self) -> None:
        exc = Exception("no status")
        exc.response = MagicMock(spec=[])  # type: ignore[attr-defined]
        assert extract_status_code(exc) is None



# ---------------------------------------------------------------------------
# _make_write_request
# ---------------------------------------------------------------------------

class TestMakeWriteRequest:

    def test_returns_response_on_success(self, mocker: Any) -> None:
        expected = {"workoutId": 99, "workoutName": "Tempo"}
        mock_fn = MagicMock(return_value=expected)
        result = _make_write_request(mock_fn, "POST", "/workout-service/workout", json={})
        assert result == expected

    def test_none_json_body_allowed_for_delete(self, mocker: Any) -> None:
        mock_fn = MagicMock(return_value=None)
        result = _make_write_request(mock_fn, "DELETE", "/workout-service/workout/1")
        assert result is None

    def test_400_raises_invalid_input_no_retry(self, mocker: Any) -> None:
        mock_sleep = mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=_http_error(400))
        with pytest.raises(GarminCliError) as exc_info:
            _make_write_request(mock_fn, "POST", "/workout-service/workout", json={})
        assert exc_info.value.error_code == "INVALID_INPUT"
        mock_sleep.assert_not_called()
        assert mock_fn.call_count == 1

    def test_401_raises_auth_failed_no_retry(self, mocker: Any) -> None:
        mock_sleep = mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=_http_error(401))
        with pytest.raises(GarminCliError) as exc_info:
            _make_write_request(mock_fn, "POST", "/workout-service/workout", json={})
        assert exc_info.value.error_code == "AUTH_FAILED"
        mock_sleep.assert_not_called()
        assert mock_fn.call_count == 1

    def test_403_raises_auth_failed_no_retry(self, mocker: Any) -> None:
        mock_sleep = mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=_http_error(403))
        with pytest.raises(GarminCliError) as exc_info:
            _make_write_request(mock_fn, "POST", "/workout-service/workout", json={})
        assert exc_info.value.error_code == "AUTH_FAILED"
        mock_sleep.assert_not_called()
        assert mock_fn.call_count == 1

    def test_404_raises_not_found_no_retry(self, mocker: Any) -> None:
        mock_sleep = mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=_http_error(404))
        with pytest.raises(GarminCliError) as exc_info:
            _make_write_request(mock_fn, "PUT", "/workout-service/workout/999", json={})
        assert exc_info.value.error_code == "NOT_FOUND"
        mock_sleep.assert_not_called()
        assert mock_fn.call_count == 1

    def test_409_raises_invalid_input_no_retry(self, mocker: Any) -> None:
        mock_sleep = mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=_http_error(409))
        with pytest.raises(GarminCliError) as exc_info:
            _make_write_request(mock_fn, "POST", "/workout-service/workout", json={})
        assert exc_info.value.error_code == "INVALID_INPUT"
        mock_sleep.assert_not_called()
        assert mock_fn.call_count == 1

    def test_429_retries_and_raises_rate_limited(self, mocker: Any) -> None:
        mock_sleep = mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=[_http_error(429)] * 4)
        with pytest.raises(GarminCliError) as exc_info:
            _make_write_request(mock_fn, "POST", "/workout-service/workout", json={})
        assert exc_info.value.error_code == "RATE_LIMITED"
        assert mock_sleep.call_count >= 1

    def test_500_retries_and_raises_server_error(self, mocker: Any) -> None:
        mock_sleep = mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=[_http_error(500)] * 4)
        with pytest.raises(GarminCliError) as exc_info:
            _make_write_request(mock_fn, "POST", "/workout-service/workout", json={})
        assert exc_info.value.error_code == "SERVER_ERROR"
        assert mock_sleep.call_count >= 1

    def test_retry_count_for_500_is_3(self, mocker: Any) -> None:
        mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=[_http_error(500)] * 4)
        with pytest.raises(GarminCliError) as exc_info:
            _make_write_request(mock_fn, "POST", "/workout-service/workout", json={})
        assert exc_info.value.error_code == "SERVER_ERROR"
        # 1 initial + 3 retries = 4 total calls
        assert mock_fn.call_count == 4

    def test_success_after_retry_returns_result(self, mocker: Any) -> None:
        mocker.patch("time.sleep")
        expected = {"workoutId": 7}
        mock_fn = MagicMock(side_effect=[_http_error(500), expected])
        result = _make_write_request(mock_fn, "POST", "/workout-service/workout", json={})
        assert result == expected

    def test_unknown_exception_reraises(self, mocker: Any) -> None:
        mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=RuntimeError("unexpected"))
        with pytest.raises(RuntimeError, match="unexpected"):
            _make_write_request(mock_fn, "POST", "/workout-service/workout", json={})
