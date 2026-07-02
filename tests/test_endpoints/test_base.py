"""Tests for _make_write_request from garmin_cli.endpoints._base and extract_status_code from garmin_cli.exceptions."""
from __future__ import annotations

import threading
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints._base import (
    _collect_daily_range,
    _make_request,
    _make_typed_request,
    _resolve_daily_call_delay,
    _resolve_fetch_concurrency,
    _resolve_retry_delays,
    _make_write_request,
)
from garmin_cli.exceptions import GarminCliError, extract_status_code
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


# ---------------------------------------------------------------------------
# _resolve_daily_call_delay
# ---------------------------------------------------------------------------

class TestMakeRequestAuthErrors:
    """Read paths must map 401/403 to AUTH_FAILED like the write path does."""

    def test_make_request_401_raises_auth_failed(self, mocker: Any) -> None:
        mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=_http_error(401))
        with pytest.raises(GarminCliError) as exc_info:
            _make_request(mock_fn, "/some/url")
        assert exc_info.value.error_code == "AUTH_FAILED"
        assert mock_fn.call_count == 1

    def test_make_request_403_raises_auth_failed(self, mocker: Any) -> None:
        mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=_http_error(403))
        with pytest.raises(GarminCliError) as exc_info:
            _make_request(mock_fn, "/some/url")
        assert exc_info.value.error_code == "AUTH_FAILED"
        assert mock_fn.call_count == 1

    def test_make_request_404_still_not_found(self, mocker: Any) -> None:
        mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=_http_error(404))
        with pytest.raises(GarminCliError) as exc_info:
            _make_request(mock_fn, "/some/url")
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_make_typed_request_401_raises_auth_failed(self, mocker: Any) -> None:
        mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=_http_error(401))
        with pytest.raises(GarminCliError) as exc_info:
            _make_typed_request(mock_fn, 123)
        assert exc_info.value.error_code == "AUTH_FAILED"
        assert mock_fn.call_count == 1

    def test_make_typed_request_403_raises_auth_failed(self, mocker: Any) -> None:
        mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=_http_error(403))
        with pytest.raises(GarminCliError) as exc_info:
            _make_typed_request(mock_fn, 123)
        assert exc_info.value.error_code == "AUTH_FAILED"


class TestResolveDailyCallDelay:

    def test_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GARMIN_CLI_DAILY_CALL_DELAY", raising=False)
        assert _resolve_daily_call_delay() == 0.5

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "0.1")
        assert _resolve_daily_call_delay() == 0.1

    def test_zero_is_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "0")
        assert _resolve_daily_call_delay() == 0.0

    def test_invalid_string_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "fast")
        assert _resolve_daily_call_delay() == 0.5

    def test_negative_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "-1")
        assert _resolve_daily_call_delay() == 0.5

    def test_empty_env_var_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "")
        assert _resolve_daily_call_delay() == 0.5

    def test_env_read_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GARMIN_CLI_DAILY_CALL_DELAY", raising=False)
        first = _resolve_daily_call_delay()
        monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "2.5")
        second = _resolve_daily_call_delay()
        assert first == 0.5
        assert second == 2.5


# ---------------------------------------------------------------------------
# _resolve_retry_delays
# ---------------------------------------------------------------------------

class TestResolveRetryDelays:

    def test_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GARMIN_CLI_RETRY_DELAYS", raising=False)
        assert _resolve_retry_delays() == [2, 4, 8]

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "1,2,4")
        assert _resolve_retry_delays() == [1.0, 2.0, 4.0]

    def test_float_values_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "0.5,1.5,3.0")
        assert _resolve_retry_delays() == [0.5, 1.5, 3.0]

    def test_invalid_string_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "not,valid")
        assert _resolve_retry_delays() == [2, 4, 8]

    def test_zero_value_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "1,0,4")
        assert _resolve_retry_delays() == [2, 4, 8]

    def test_negative_value_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "1,-2,4")
        assert _resolve_retry_delays() == [2, 4, 8]

    def test_empty_env_var_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "")
        assert _resolve_retry_delays() == [2, 4, 8]

    def test_env_read_at_call_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GARMIN_CLI_RETRY_DELAYS", raising=False)
        first = _resolve_retry_delays()
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "5,10")
        second = _resolve_retry_delays()
        assert first == [2, 4, 8]
        assert second == [5.0, 10.0]

    def test_retry_loop_uses_env_delay(
        self, monkeypatch: pytest.MonkeyPatch, mocker: Any
    ) -> None:
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "0.1")
        mock_sleep = mocker.patch("time.sleep")
        mock_fn = MagicMock(side_effect=[_http_error(429), _http_error(429)])
        with pytest.raises(GarminCliError) as exc_info:
            _make_write_request(mock_fn, "POST", "/test", json={})
        assert exc_info.value.error_code == "RATE_LIMITED"
        mock_sleep.assert_called_once_with(0.1)


# ---------------------------------------------------------------------------
# _resolve_fetch_concurrency
# ---------------------------------------------------------------------------

class TestResolveFetchConcurrency:

    def test_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GARMIN_CLI_FETCH_CONCURRENCY", raising=False)
        assert _resolve_fetch_concurrency() == 4

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_FETCH_CONCURRENCY", "2")
        assert _resolve_fetch_concurrency() == 2

    def test_fraction_truncates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_FETCH_CONCURRENCY", "2.9")
        assert _resolve_fetch_concurrency() == 2

    @pytest.mark.parametrize("raw", ["0", "-1", "fast", "", "0.4", "inf", "-inf", "nan"])
    def test_non_positive_or_invalid_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        monkeypatch.setenv("GARMIN_CLI_FETCH_CONCURRENCY", raw)
        assert _resolve_fetch_concurrency() == 4


# ---------------------------------------------------------------------------
# _collect_daily_range
# ---------------------------------------------------------------------------

class TestCollectDailyRange:

    def test_empty_range_returns_empty_list(self) -> None:
        getter = MagicMock()
        assert _collect_daily_range(getter, date(2026, 3, 12), date(2026, 3, 11)) == []
        getter.assert_not_called()

    def test_single_day_runs_inline_without_threads(self) -> None:
        calling_threads: list[threading.Thread] = []

        def getter(day: date) -> str:
            calling_threads.append(threading.current_thread())
            return day.isoformat()

        result = _collect_daily_range(getter, date(2026, 3, 11), date(2026, 3, 11))
        assert result == ["2026-03-11"]
        assert calling_threads == [threading.current_thread()]

    def test_results_ordered_by_date_despite_completion_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The first day is forced to finish last; results must still come
        back in date-ascending order."""
        monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "0")
        monkeypatch.setenv("GARMIN_CLI_FETCH_CONCURRENCY", "4")
        gate = threading.Event()

        def getter(day: date) -> str:
            if day == date(2026, 3, 13):
                gate.set()
            elif day == date(2026, 3, 11):
                assert gate.wait(timeout=10), "last day never started"
            return day.isoformat()

        result = _collect_daily_range(getter, date(2026, 3, 11), date(2026, 3, 13))
        assert result == ["2026-03-11", "2026-03-12", "2026-03-13"]

    def test_exception_from_any_day_propagates_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GARMIN_CLI_DAILY_CALL_DELAY", "0")

        def getter(day: date) -> dict:
            if day == date(2026, 3, 12):
                raise GarminCliError(error="boom", error_code="SERVER_ERROR")
            return {}

        with pytest.raises(GarminCliError) as exc_info:
            _collect_daily_range(getter, date(2026, 3, 11), date(2026, 3, 14))
        assert exc_info.value.error_code == "SERVER_ERROR"
        assert exc_info.value.error == "boom"

    def test_sleeps_between_submissions(self, mocker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """The rate-limit delay applies between task submissions: n days ->
        n-1 sleeps of the configured delay, same ceiling as the old serial loop."""
        monkeypatch.delenv("GARMIN_CLI_DAILY_CALL_DELAY", raising=False)
        mock_sleep = mocker.patch("garmin_cli.endpoints._base.time.sleep")
        getter = MagicMock(return_value={})

        result = _collect_daily_range(getter, date(2026, 3, 11), date(2026, 3, 13))

        assert result == [{}, {}, {}]
        assert getter.call_count == 3
        assert mock_sleep.call_args_list == [((0.5,),), ((0.5,),)]
