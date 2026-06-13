"""Shared HTTP request helper with retry/error handling for Garmin endpoints."""
from __future__ import annotations

import os
import time
from datetime import date, timedelta
from typing import Any, Callable

from garmin_cli._env import _env_float
from garmin_cli.exceptions import GarminCliError, extract_status_code

_RETRY_DELAYS: list[float] = [2, 4, 8]
_DEFAULT_DAILY_CALL_DELAY: float = 0.5

# Shared immediate-fail policy across read, typed, and write helpers: auth
# rejections and not-found never retry. Per-helper maps extend this (writes add
# 400/409; the URL read overrides 404 with the URL-bearing message).
_AUTH_NOT_FOUND_ERRORS: dict[int, tuple[str, str]] = {
    401: ("Authentication failed.", "AUTH_FAILED"),
    403: ("Authentication failed.", "AUTH_FAILED"),
    404: ("Not found.", "NOT_FOUND"),
}


def _resolve_daily_call_delay() -> float:
    """Return the inter-call delay (seconds) used by ``_collect_daily_range``.

    Reads ``GARMIN_CLI_DAILY_CALL_DELAY`` from the environment as a
    non-negative float.  Any parse error or negative value causes the whole
    env var to be ignored and the default (0.5 s) is used instead.
    """
    return _env_float("GARMIN_CLI_DAILY_CALL_DELAY", _DEFAULT_DAILY_CALL_DELAY)


def _resolve_retry_delays() -> list[float]:
    """Return the configured retry delay sequence.

    Reads ``GARMIN_CLI_RETRY_DELAYS`` from the environment as a
    comma-separated list of positive floats (e.g. ``"1,2,4"``).  Any parse
    error or non-positive value causes the whole env var to be ignored and
    the default ``[2, 4, 8]`` is used instead.
    """
    raw = os.environ.get("GARMIN_CLI_RETRY_DELAYS", "")
    if raw:
        try:
            delays = [float(s.strip()) for s in raw.split(",")]
            if delays and all(d > 0 for d in delays):
                return delays
        except ValueError:
            pass
    return list(_RETRY_DELAYS)


def _validate_numeric_id(value: Any, name: str) -> int:
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        raise GarminCliError(
            error=f"{name} must be a valid integer",
            error_code="INVALID_INPUT",
        ) from exc


def _retry_loop(
    call: Callable[[], Any],
    *,
    immediate_errors: dict[int, tuple[str, str]] | None = None,
) -> Any:
    """Execute *call* with retry on 429/5xx.

    Garth's urllib3 transport retries GET/PUT/DELETE automatically, but not
    POST.  This loop provides retry coverage for POST write operations and
    acts as a safety net for the other methods.

    Args:
        call: Zero-arg callable that performs the API request.
        immediate_errors: Maps HTTP status codes to (error_message, error_code)
            tuples for errors that should raise immediately without retry.
    """
    delays = _resolve_retry_delays()
    for attempt in range(len(delays) + 1):
        try:
            return call()
        except Exception as exc:
            code = extract_status_code(exc)

            if immediate_errors is not None and code in immediate_errors:
                error_msg, error_code = immediate_errors[code]
                raise GarminCliError(error=error_msg, error_code=error_code) from exc

            if code == 429:
                if attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                raise GarminCliError(
                    error="Rate limited by Garmin API.", error_code="RATE_LIMITED"
                ) from exc

            if code is not None and code >= 500:
                if attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                raise GarminCliError(
                    error="Garmin API server error.", error_code="SERVER_ERROR"
                ) from exc

            raise


def _make_write_request(
    connectapi_fn: Callable[..., Any],
    method: str,
    url: str,
    *,
    json: dict[str, Any] | None = None,
) -> Any:
    """Execute a write operation (POST/PUT/DELETE) via connectapi_fn with retry on 429/5xx."""
    return _retry_loop(
        lambda: connectapi_fn(url, method=method, json=json),
        immediate_errors={
            **_AUTH_NOT_FOUND_ERRORS,
            400: ("Invalid input.", "INVALID_INPUT"),
            409: ("Invalid input.", "INVALID_INPUT"),
        },
    )


def _make_request(
    connectapi_fn: Callable[..., Any],
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    """Execute url via connectapi_fn with exponential backoff on 429/5xx.

    Passes connectapi_fn by reference so callers can patch their local
    ``garth`` module in tests without affecting this shared helper.
    """
    return _retry_loop(
        lambda: connectapi_fn(url, params=params),
        immediate_errors={
            **_AUTH_NOT_FOUND_ERRORS,
            404: (f"Not found: {url}", "NOT_FOUND"),
        },
    )


def _make_typed_request(typed_method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute a typed backend-adapter method with retry on 429/5xx.

    Used for python-garminconnect typed methods (get_activity_typed_splits,
    get_activity_details, get_activity_hr_in_timezones) that take the
    activity id directly rather than a URL string.
    """
    return _retry_loop(
        lambda: typed_method(*args, **kwargs),
        immediate_errors=_AUTH_NOT_FOUND_ERRORS,
    )


def _collect_daily_range(
    getter: Callable[[date], Any],
    start: date,
    end: date,
) -> list[Any]:
    delay = _resolve_daily_call_delay()
    items: list[Any] = []
    current = start
    while current <= end:
        items.append(getter(current))
        current += timedelta(days=1)
        if current <= end:
            time.sleep(delay)
    return items
