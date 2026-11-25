"""Shared HTTP request helper with retry/error handling for Garmin endpoints."""
from __future__ import annotations

import math
import os
import time
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any, Callable

from garmin_cli._env import _env_float
from garmin_cli.exceptions import (
    TRANSIENT_KINDS,
    GarminCliError,
    extract_status_code,
    failure_kind,
    may_have_been_processed,
    upstream_error,
)
from garmin_cli.workout_schema import is_positive_id

_RETRY_DELAYS: list[float] = [2, 4, 8]
# Retried unless retry_transient=False; rate limits are always retried.
_RETRYABLE_FAILURES = TRANSIENT_KINDS - {"throttled"}
_DEFAULT_DAILY_CALL_DELAY: float = 0.5
_DEFAULT_FETCH_CONCURRENCY: int = 4

# Immediate-fail messages by status (401/403 and other 4xx are classified in
# _retry_loop). Writes add 400/409; the URL read overrides 404 with the URL.
_NOT_FOUND_ERRORS: dict[int, tuple[str, str]] = {404: ("Not found.", "NOT_FOUND")}


def _resolve_daily_call_delay() -> float:
    """Return the inter-submission delay (seconds) used by ``_fan_out``.

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

    Shared by the fan-out call sites (multisport children, report sections,
    reconciliation details) so the worker-cap arithmetic lives in one place;
    ``_fan_out`` sizes its own pool because it also needs the worker count.
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
    """Accept a positive int or an ASCII digit string of at most 20 digits (CLI arguments) only."""
    error = GarminCliError(error=f"{name} must be a positive integer", error_code="INVALID_INPUT")
    parsed = value
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 20:
        try:
            parsed = int(value)
        except ValueError as exc:  # defensive: int() limits differ across interpreters
            raise error from exc
    if not is_positive_id(parsed):
        raise error
    return parsed


def _retry_loop(
    call: Callable[[], Any],
    *,
    immediate_errors: dict[int, tuple[str, str]] | None = None,
    retry_transient: bool = True,
    gone_after_retry_is_done: bool = False,
) -> Any:
    """Execute *call*, retrying rate limits and (by default) 5xx/network failures.

    This loop is the only retry layer for reads and writes alike: the backend
    builds its ``Garmin`` clients with upstream ``retry_attempts=0``, and the
    shared ``requests.Session`` mounts no urllib3 ``Retry`` (verified against
    garminconnect 0.3.20).

    Upstream HTTP and transport failures leave as ``GarminCliError``:
    RATE_LIMITED (429/427), AUTH_FAILED (401/403), SERVER_ERROR (5xx),
    NETWORK_ERROR (connection errors and timeouts), INVALID_INPUT (any other
    4xx). Other exceptions propagate unchanged.

    Args:
        call: Zero-arg callable that performs the API request.
        immediate_errors: Maps HTTP status codes to (error_message, error_code)
            tuples for errors that should raise immediately without retry.
        retry_transient: False retries only rate limits, for requests that
            must not be repeated after a 5xx or timeout (the server may have
            applied them) or that should fail fast.
        gone_after_retry_is_done: For deletes: a 404 on a retry after a 5xx or
            read timeout means the earlier attempt already removed it, so
            the call succeeds (returns None).
    """
    delays = _resolve_retry_delays()
    maybe_processed = False
    for attempt in range(len(delays) + 1):
        try:
            return call()
        except GarminCliError:
            raise
        except Exception as exc:
            code = extract_status_code(exc)
            if gone_after_retry_is_done and maybe_processed and code == 404:
                return None

            if immediate_errors is not None and code in immediate_errors:
                error_msg, error_code = immediate_errors[code]
                raise GarminCliError(
                    error=error_msg, error_code=error_code, may_have_landed=maybe_processed
                ) from exc

            kind = failure_kind(exc)
            maybe_processed = maybe_processed or may_have_been_processed(exc)
            retryable = kind == "throttled" or (retry_transient and kind in _RETRYABLE_FAILURES)
            if retryable and attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            error = upstream_error(kind, code)
            if error is None:
                raise
            # A 429/401 after a 5xx does not undo what the 5xx attempt may have applied.
            error.may_have_landed = maybe_processed
            raise error from exc


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
        immediate_errors={404: (f"Not found: {url}", "NOT_FOUND")},
    )


def _make_typed_request(typed_method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute a typed backend-adapter method with retry on 429/5xx.

    Used for python-garminconnect typed methods (get_activity_typed_splits,
    get_activity_details, get_activity_hr_in_timezones) that take the
    activity id directly rather than a URL string.
    """
    return _retry_loop(
        lambda: typed_method(*args, **kwargs),
        immediate_errors=_NOT_FOUND_ERRORS,
    )


_WRITE_ERRORS: dict[int, tuple[str, str]] = {
    **_NOT_FOUND_ERRORS,
    400: ("Invalid input.", "INVALID_INPUT"),
    409: ("Invalid input.", "INVALID_INPUT"),
}


def _make_typed_write(typed_method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute an idempotent typed write (PUT/DELETE) with retry on 429/5xx/network.

    Same as :func:`_make_typed_request` but with the write-verb immediate-fail
    map (400/409 -> INVALID_INPUT), so a
    Garmin payload rejection or conflict surfaces as a classified
    ``GarminCliError`` instead of escaping the retry loop raw.
    """
    return _retry_loop(lambda: typed_method(*args, **kwargs), immediate_errors=_WRITE_ERRORS)


def _make_typed_delete(typed_method: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Like :func:`_make_typed_write`, but a 404 on a retry after a 5xx/timeout is success."""
    _retry_loop(
        lambda: typed_method(*args, **kwargs),
        immediate_errors=_WRITE_ERRORS,
        gone_after_retry_is_done=True,
    )


def _make_typed_create(typed_method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute a non-idempotent typed POST (create/schedule/upload).

    Retried only on rate limits, which Garmin rejects unprocessed: a 5xx or
    timeout may already have created the resource, so repeating it could
    duplicate it.
    """
    return _retry_loop(
        lambda: typed_method(*args, **kwargs),
        immediate_errors=_WRITE_ERRORS,
        retry_transient=False,
    )


def _collect_daily_range(
    getter: Callable[[date], Any],
    start: date,
    end: date,
) -> list[Any]:
    """Fetch one payload per day in ``[start, end]``, ordered by date ascending."""
    return _fan_out(getter, _dates(start, end))


def _dates(start: date, end: date) -> list[date]:
    """Every date in ``[start, end]`` ascending; empty when start > end, safe at ``date.max``."""
    days: list[date] = []
    day = start
    while day <= end:
        days.append(day)
        if day == end:
            break
        day += timedelta(days=1)
    return days


def _fan_out[T](fetch: Callable[[T], Any], items: list[T]) -> list[Any]:
    """Call ``fetch`` for each item on a bounded thread pool; results in item order.

    At most a pool's worth of calls is in flight, and submissions are at least
    the per-call delay apart (time spent waiting for a worker counts toward
    it), so the request-rate ceiling matches a serial loop while requests
    overlap the waiting.  Once a failure is observed no further items are
    submitted; the first failing item (in item order) propagates its
    exception unchanged after earlier items finish.
    """
    if not items:
        return []
    if len(items) == 1:
        return [fetch(items[0])]

    delay = _resolve_daily_call_delay()
    workers = min(len(items), _resolve_fetch_concurrency())
    futures: list[Future[Any]] = []

    def failed() -> bool:
        return any(f.done() and f.exception() is not None for f in futures)

    with ThreadPoolExecutor(max_workers=workers) as pool, _cancel_futures_on_error(futures):
        next_submit = time.monotonic()
        for item in items:
            if futures:
                running = [f for f in futures if not f.done()]
                if len(running) >= workers:
                    wait(running, return_when=FIRST_COMPLETED)
                if failed():
                    break
                remaining = next_submit - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                if failed():
                    break
            futures.append(pool.submit(fetch, item))
            next_submit = time.monotonic() + delay
        return [future.result() for future in futures]
