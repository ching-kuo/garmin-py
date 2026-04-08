"""Shared HTTP request helper with retry/error handling for Garmin endpoints."""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any, Callable

from garmin_cli.exceptions import GarminCliError

_RETRY_DELAYS: list[int] = [2, 4, 8]


def _validate_numeric_id(value: Any, name: str) -> int:
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        raise GarminCliError(
            error=f"{name} must be a valid integer",
            error_code="INVALID_INPUT",
        ) from exc


def extract_status_code(exc: Exception) -> int | None:
    if hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        return exc.response.status_code
    # GarthHTTPError stores the HTTPError at exc.error.response.status_code
    if hasattr(exc, "error") and hasattr(exc.error, "response") and hasattr(exc.error.response, "status_code"):
        return exc.error.response.status_code
    return None


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
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            return call()
        except Exception as exc:
            code = extract_status_code(exc)

            if immediate_errors is not None and code in immediate_errors:
                error_msg, error_code = immediate_errors[code]
                raise GarminCliError(error=error_msg, error_code=error_code) from exc

            if code == 429:
                if attempt < len(_RETRY_DELAYS):
                    time.sleep(_RETRY_DELAYS[attempt])
                    continue
                raise GarminCliError(
                    error="Rate limited by Garmin API.", error_code="RATE_LIMITED"
                ) from exc

            if code is not None and code >= 500:
                if attempt < len(_RETRY_DELAYS):
                    time.sleep(_RETRY_DELAYS[attempt])
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
            400: ("Invalid input.", "INVALID_INPUT"),
            401: ("Authentication failed.", "AUTH_FAILED"),
            403: ("Authentication failed.", "AUTH_FAILED"),
            404: ("Not found.", "NOT_FOUND"),
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
            404: (f"Not found: {url}", "NOT_FOUND"),
        },
    )


def _collect_daily_range(
    getter: Callable[[date], Any],
    start: date,
    end: date,
) -> list[Any]:
    items: list[Any] = []
    current = start
    while current <= end:
        items.append(getter(current))
        current += timedelta(days=1)
        if current <= end:
            time.sleep(0.5)
    return items
