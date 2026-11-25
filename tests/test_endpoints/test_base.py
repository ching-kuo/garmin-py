"""Tests for garmin_cli.endpoints._base helpers and extract_status_code from garmin_cli.exceptions."""
from __future__ import annotations

import socket
import ssl
import threading
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import curl_cffi.requests.exceptions as curl_errors
import pytest
import requests
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from garmin_cli.endpoints._base import (
    _collect_daily_range,
    _make_request,
    _make_typed_create,
    _make_typed_request,
    _make_typed_write,
    _resolve_daily_call_delay,
    _resolve_fetch_concurrency,
    _resolve_retry_delays,
)
from garmin_cli.exceptions import (
    GarminCliError,
    extract_status_code,
    failure_kind,
    login_error,
    may_have_been_processed,
)
from tests.helpers import make_http_error as _http_error
from tests.helpers import make_requests_http_error


def _chained(outer: Exception, cause: BaseException) -> Exception:
    """``raise outer from cause``, as upstream wraps transport errors."""
    try:
        raise outer from cause
    except Exception as exc:
        return exc


class TestFailureKind:

    @pytest.mark.parametrize(
        ("exc", "kind"),
        [
            # Upstream's profile load wraps 503s and timeouts as AuthenticationError.
            (_chained(GarminConnectAuthenticationError("Failed to retrieve social profile"), _http_error(503)), "server"),
            (_chained(GarminConnectAuthenticationError("Failed to retrieve social profile"), requests.Timeout("t")), "unreachable"),
            (GarminConnectAuthenticationError("DI token refresh failed"), "rejected"),
            (make_requests_http_error(401), "rejected"),
            (make_requests_http_error(408), "server"),
            (make_requests_http_error(425), "server"),
            (make_requests_http_error(400), "client"),
            (requests.exceptions.ChunkedEncodingError("broken"), "unreachable"),
            (socket.gaierror("name resolution"), "unreachable"),
            (ssl.SSLError("handshake"), "unreachable"),
            (curl_errors.Timeout("curl timeout"), "unreachable"),
            (curl_errors.ConnectionError("curl reset"), "unreachable"),
            (curl_errors.ProxyError("proxy refused"), "unreachable"),
            (curl_errors.IncompleteRead("short body"), "unreachable"),
            # Status-less upstream errors without a transport cause are local, not network.
            (GarminConnectConnectionError("Connection error: Expecting value: line 1"), "other"),
            (GarminConnectConnectionError("curl_cffi not available"), "other"),
            (GarminConnectConnectionError("Display name is not set"), "other"),
            # Outside login, a bot-challenge body never overrides the status.
            (_http_error(503, "API Error 503 - Cloudflare bot challenge"), "server"),
        ],
    )
    def test_classifies_upstream_shapes(self, exc: Exception, kind: str) -> None:
        assert failure_kind(exc) == kind

    @pytest.mark.parametrize(
        ("message", "code"),
        [
            (
                "All login strategies exhausted: Mobile sign-in page: HTTP 403 "
                "(Cloudflare bot challenge) — falling through to next strategy",
                "RATE_LIMITED",
            ),
            ("All login strategies exhausted: Portal login: unexpected page", "NETWORK_ERROR"),
            ("All login strategies exhausted: Mobile login failed: HTTP 502, body", "SERVER_ERROR"),
            ("All login strategies exhausted: Widget login: HTTP 401", "AUTH_FAILED"),
        ],
    )
    def test_login_error_for_unchained_sso_exhaustion(self, message: str, code: str) -> None:
        # garminconnect 0.3.20: sso.py raises this unchained; Garmin.login
        # re-wraps it as "Login failed: ..." from the original.
        inner = GarminConnectConnectionError(message)
        assert login_error(_chained(GarminConnectConnectionError(f"Login failed: {inner}"), inner)).error_code == code
        assert login_error(inner).error_code == code

    @pytest.mark.parametrize(
        ("exc", "processed"),
        [
            (make_requests_http_error(503), True),
            (requests.ReadTimeout("read"), True),
            (requests.ConnectTimeout("connect"), False),
            (requests.ConnectionError("refused"), False),
            (socket.gaierror("dns"), False),
            (curl_errors.ConnectTimeout("connect"), False),
        ],
    )
    def test_may_have_been_processed(self, exc: Exception, processed: bool) -> None:
        assert may_have_been_processed(exc) is processed

    def test_timeout_while_handling_a_rate_limit_is_not_throttled(self) -> None:
        # Training-plan compensation: an unschedule times out inside the
        # handler for an earlier RATE_LIMITED failure.
        try:
            try:
                raise GarminCliError("Rate limited by Garmin API.", "RATE_LIMITED") from _http_error(429)
            except GarminCliError:
                raise requests.Timeout("read timed out")
        except requests.Timeout as exc:
            assert failure_kind(exc) == "unreachable"

    def test_suppressed_context_is_ignored(self) -> None:
        try:
            try:
                raise requests.Timeout("t")
            except requests.Timeout:
                raise ValueError("bad payload") from None
        except ValueError as exc:
            assert failure_kind(exc) == "other"


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

    @pytest.mark.parametrize(
        "message",
        [
            "HTTPSConnectionPool(host='connectapi.garmin.com', port=443): Read timed out.",
            "Connection error: /workout-service/workout/502 reset by peer",
            "loaded 200 activities",
            "ride (429).fit",
            "cadence (401) out of range",
            "connect failed (443)",
        ],
    )
    def test_bare_three_digit_numbers_are_not_statuses(self, message: str) -> None:
        assert extract_status_code(Exception(message)) is None

    def test_reads_explicit_status_text_on_a_chained_link(self) -> None:
        try:
            raise Exception("Connection error: upstream failed") from Exception("API Error 503")
        except Exception as outer:
            assert extract_status_code(outer) == 503

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("API Error 503 - Service Unavailable", 503),
            ("API Error (429)", 429),
            ("HTTP Error 503: Service Unavailable", 503),
            ("Server error (500) while saving", 500),
            ("Login failed: HTTP 500, body omitted", 500),
            ("unexpected status code 502", 502),
            ("API call client error (422): bad", 422),
            ("503 Server Error: Service Unavailable for url: https://x", 503),
        ],
    )
    def test_explicit_status_patterns_match(self, message: str, expected: int) -> None:
        assert extract_status_code(Exception(message)) == expected

    def test_prefers_response_in_cause_chain_over_message(self) -> None:
        inner = _http_error(429)
        try:
            raise Exception("port=443 failed") from inner
        except Exception as outer:
            assert extract_status_code(outer) == 429



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


class TestRetryLoopClassification:
    """Every upstream HTTP/transport failure leaves the loop as a GarminCliError."""

    @pytest.fixture(autouse=True)
    def _fast(self, mocker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        mocker.patch("time.sleep")
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "1,2,3")

    @pytest.mark.parametrize(
        "exc",
        [
            GarminConnectTooManyRequestsError("Mobile SSO login returned 427"),
            GarminConnectTooManyRequestsError("Rate limit exceeded"),
        ],
    )
    def test_too_many_requests_error_is_rate_limited(self, exc: Exception) -> None:
        mock_fn = MagicMock(side_effect=exc)
        with pytest.raises(GarminCliError) as exc_info:
            _make_request(mock_fn, "/some/url")
        assert exc_info.value.error_code == "RATE_LIMITED"
        assert mock_fn.call_count == 4

    @pytest.mark.parametrize(
        "exc",
        [
            requests.ConnectionError("HTTPSConnectionPool(host='x', port=443): refused"),
            requests.Timeout("read timed out"),
            TimeoutError("timed out"),
            _chained(GarminConnectConnectionError("Connection error: reset"), requests.ConnectionError("reset")),
        ],
    )
    def test_transport_failures_become_network_error_after_retries(self, exc: Exception) -> None:
        mock_fn = MagicMock(side_effect=exc)
        with pytest.raises(GarminCliError) as exc_info:
            _make_request(mock_fn, "/some/url")
        assert exc_info.value.error_code == "NETWORK_ERROR"
        assert exc_info.value.error == "Could not reach Garmin."
        assert mock_fn.call_count == 4

    @pytest.mark.parametrize("status", [400, 405, 409, 422])
    def test_other_4xx_on_read_is_invalid_input_with_status(self, status: int) -> None:
        mock_fn = MagicMock(side_effect=_http_error(status))
        with pytest.raises(GarminCliError) as exc_info:
            _make_request(mock_fn, "/some/url")
        assert exc_info.value.error_code == "INVALID_INPUT"
        assert str(status) in exc_info.value.error
        assert mock_fn.call_count == 1

    def test_status_less_auth_error_is_auth_failed(self) -> None:
        mock_fn = MagicMock(side_effect=GarminConnectAuthenticationError("DI token refresh failed"))
        with pytest.raises(GarminCliError) as exc_info:
            _make_typed_request(mock_fn)
        assert exc_info.value.error_code == "AUTH_FAILED"
        assert mock_fn.call_count == 1

    def test_id_like_502_in_message_is_not_a_server_error(self) -> None:
        mock_fn = MagicMock(side_effect=ValueError("bad payload for /workout/502"))
        with pytest.raises(ValueError):
            _make_typed_request(mock_fn)
        assert mock_fn.call_count == 1


class TestNonIdempotentWrites:
    """Creates retry only on rate limits: a 5xx or timeout may have been applied."""

    @pytest.fixture(autouse=True)
    def _fast(self, mocker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        mocker.patch("time.sleep")
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "1,2,3")

    @pytest.mark.parametrize(
        ("exc", "code"),
        [
            (_http_error(500), "SERVER_ERROR"),
            (requests.Timeout("read"), "NETWORK_ERROR"),
            # A bot-challenge body on a data call is still a 5xx: never replay the create.
            (_http_error(503, "API Error 503 - Cloudflare bot challenge"), "SERVER_ERROR"),
        ],
    )
    def test_create_is_not_retried_on_5xx_or_network(self, exc: Exception, code: str) -> None:
        mock_fn = MagicMock(side_effect=exc)
        with pytest.raises(GarminCliError) as exc_info:
            _make_typed_create(mock_fn, {"x": 1})
        assert exc_info.value.error_code == code
        assert mock_fn.call_count == 1

    def test_create_retries_on_429(self) -> None:
        mock_fn = MagicMock(side_effect=[_http_error(429), {"ok": True}])
        assert _make_typed_create(mock_fn) == {"ok": True}
        assert mock_fn.call_count == 2

    def test_idempotent_write_still_retries_on_5xx(self) -> None:
        mock_fn = MagicMock(side_effect=[_http_error(503), None])
        assert _make_typed_write(mock_fn, 1) is None
        assert mock_fn.call_count == 2


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
            _make_request(mock_fn, "/test")
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
