"""Shared HTTP request helper with retry/error handling for Garmin endpoints."""
from __future__ import annotations

import math
import os
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any, Callable

from garmin_cli._env import _env_float
from garmin_cli.exceptions import GarminCliError, extract_status_code

_RETRY_DELAYS: list[float] = [2, 4, 8]
_DEFAULT_DAILY_CALL_DELAY: float = 0.5
_DEFAULT_FETCH_CONCURRENCY: int = 4

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


def _resolve_fetch_concurrency() -> int:
    """Return the worker cap for concurrent fan-out fetches.

    Reads ``GARMIN_CLI_FETCH_CONCURRENCY`` from the environment as a positive
    number (fractions are truncated).  Any parse error or non-positive value
    causes the whole env var to be ignored and the default (4) is used
    instead.  Kept deliberately small: Garmin rate-limits aggressively.
    """
    raw = _env_float("GARMIN_CLI_FETCH_CONCURRENCY", _DEFAULT_FETCH_CONCURRENCY, allow_zero=False)
    if not math.isfinite(raw):
        return _DEFAULT_FETCH_CONCURRENCY
    value = int(raw)
    return value if value > 0 else _DEFAULT_FETCH_CONCURRENCY


def _bounded_thread_pool(task_count: int) -> ThreadPoolExecutor:
    """ThreadPoolExecutor sized to ``min(task_count, _resolve_fetch_concurrency())``.

    Shared by the fan-out call sites (daily-range collection, multisport
    children, report sections) so the worker-cap arithmetic lives in one
    place.
    """
    return ThreadPoolExecutor(max_workers=min(task_count, _resolve_fetch_concurrency()))


@contextmanager
def _cancel_futures_on_error(futures: list[Future[Any]]) -> Iterator[None]:
    """Cancel all *futures* if the wrapped block raises, then propagate.

    Used by fan-out call sites so an error partway through draws down
    outstanding work instead of leaving orphaned tasks on the pool.
    """
    try:
        yield
    except BaseException:
        for future in futures:
            future.cancel()
        raise


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

    The python-garminconnect backend sends each API call on a fresh plain
    ``requests.Session`` with no urllib3 ``Retry`` mounted, so this loop is
    the only retry layer for reads and writes alike (verified against
    garminconnect 0.3.2 ``Client._run_request``).

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


def _make_typed_write(typed_method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute a typed backend-adapter write method with retry on 429/5xx.

    Same as :func:`_make_typed_request` but with the write-verb immediate-fail
    map (400/409 -> INVALID_INPUT), matching :func:`_make_write_request`, so a
    Garmin payload rejection or conflict surfaces as a classified
    ``GarminCliError`` instead of escaping the retry loop raw.
    """
    return _retry_loop(
        lambda: typed_method(*args, **kwargs),
        immediate_errors={
            **_AUTH_NOT_FOUND_ERRORS,
            400: ("Invalid input.", "INVALID_INPUT"),
            409: ("Invalid input.", "INVALID_INPUT"),
        },
    )


def _collect_daily_range(
    getter: Callable[[date], Any],
    start: date,
    end: date,
) -> list[Any]:
    """Fetch one payload per day in ``[start, end]``, ordered by date ascending.

    Days are fetched on a bounded thread pool.  The per-call delay is applied
    between task *submissions*, so the request-rate ceiling matches the old
    serial implementation while requests overlap the waiting.  The first
    failing day (in date order) propagates its exception unchanged; once a
    failure is observed no further days are submitted, and in-flight work is
    drained before raising.
    """
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    if not days:
        return []
    if len(days) == 1:
        return [getter(days[0])]

    delay = _resolve_daily_call_delay()
    futures: list[Future[Any]] = []
    with _bounded_thread_pool(len(days)) as pool, _cancel_futures_on_error(futures):
        for index, day in enumerate(days):
            futures.append(pool.submit(getter, day))
            if index < len(days) - 1:
                if any(f.done() and f.exception() is not None for f in futures):
                    break
                time.sleep(delay)
        return [future.result() for future in futures]
