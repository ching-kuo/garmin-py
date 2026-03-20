"""Shared HTTP request helper with retry/error handling for Garmin endpoints."""
from __future__ import annotations

import time
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


def _status_code(exc: Exception) -> int | None:
    if hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        return exc.response.status_code
    # GarthHTTPError stores the HTTPError at exc.error.response.status_code
    if hasattr(exc, "error") and hasattr(exc.error, "response") and hasattr(exc.error.response, "status_code"):
        return exc.error.response.status_code
    return None


def _make_write_request(
    connectapi_fn: Callable[..., Any],
    method: str,
    url: str,
    *,
    json: dict[str, Any] | None = None,
) -> Any:
    """Execute a write operation (POST/PUT/DELETE) via connectapi_fn with retry on 429/5xx."""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            return connectapi_fn(url, method=method, json=json)
        except Exception as exc:
            code = _status_code(exc)

            if code == 400 or code == 409:
                raise GarminCliError(
                    error="Invalid input.", error_code="INVALID_INPUT"
                ) from exc

            if code == 401 or code == 403:
                raise GarminCliError(
                    error="Authentication failed.", error_code="AUTH_FAILED"
                ) from exc

            if code == 404:
                raise GarminCliError(
                    error="Not found.", error_code="NOT_FOUND"
                ) from exc

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
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            return connectapi_fn(url, params=params)
        except Exception as exc:
            code = _status_code(exc)

            if code == 404:
                raise GarminCliError(
                    error=f"Not found: {url}", error_code="NOT_FOUND"
                ) from exc

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
