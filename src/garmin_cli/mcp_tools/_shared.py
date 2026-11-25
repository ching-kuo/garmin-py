"""Shared infrastructure for the per-domain MCP tool registrars.

Holds the input validation, envelope/error translation, auth wrapper, and the
multi-section report fan-out that every domain module builds on. ``ensure_
authenticated`` is bound here so read tools uniformly gate on
``garmin_cli.mcp_tools._shared.ensure_authenticated``; write tools call it
inline at their own module scope instead.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import Future
from datetime import date, timedelta
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from garmin_cli.auth import ensure_authenticated
from garmin_cli.config import CliConfig
from garmin_cli.date_utils import today
from garmin_cli.endpoints._base import (
    _bounded_thread_pool,
    _cancel_futures_on_error,
    _resolve_retry_delays,
)
from garmin_cli.error_contracts import error_contract
from garmin_cli.exceptions import GarminCliError
from garmin_cli.mcp_tools._schemas import Envelope
from garmin_cli.workout_schema import is_positive_id

_MAX_DAYS = 90

# Tool id parameter type: strict, so JSON true, 1.0 and "1" fail schema
# validation instead of being coerced to 1 and reaching a (destructive) handler.
StrictId = Annotated[int, Field(strict=True)]

# Range-tool parameters: start_date or days, end_date defaulting to today.
EndDate = Annotated[str | None, Field(description="YYYY-MM-DD; default today")]
Days = Annotated[
    int | None,
    Field(strict=True, ge=1, le=_MAX_DAYS, description="last N days ending end_date; instead of start_date"),
]


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ToolError(f"Invalid date format for {name}: expected YYYY-MM-DD, got '{value}'") from exc


def _check_range(start: date, end: date) -> tuple[date, date]:
    if start > end:
        raise ToolError(f"start_date must be on or before end_date: {start} > {end}")
    span = (end - start).days + 1
    if span > _MAX_DAYS:
        raise ToolError(f"Date range cannot exceed {_MAX_DAYS} days (got {span} days)")
    return start, end


def _parse_date_range(start_date: str, end_date: str) -> tuple[date, date]:
    return _check_range(_parse_date(start_date, "start_date"), _parse_date(end_date, "end_date"))


def _date_window(
    start_date: str | None, end_date: str | None, days: int | None
) -> Callable[[], tuple[date, date]]:
    """Validate a range given as start_date or days, with end_date defaulting to today.

    Explicit dates are checked now (before auth). The returned thunk resolves
    the window; call it after auth so a defaulted end_date is today in the
    athlete's Garmin profile timezone.
    """
    # The Days schema already holds days to a strict 1-90 integer.
    if days is not None and start_date is not None:
        raise ToolError("Pass either start_date or days, not both")
    if days is None and start_date is None:
        raise ToolError("Pass start_date or days")
    start = _parse_date(start_date, "start_date") if start_date is not None else None

    def resolve(last: date) -> tuple[date, date]:
        if start is not None:
            return _check_range(start, last)
        try:
            # days is set whenever start is None (checked above).
            return _check_range(last - timedelta(days=(days or 1) - 1), last)
        except OverflowError as exc:
            raise ToolError(f"days={days} ending {last} reaches before 0001-01-01") from exc

    if end_date is not None:
        window = resolve(_parse_date(end_date, "end_date"))
        return lambda: window
    return lambda: resolve(today())


def _validate_positive_id(value: int, name: str) -> int:
    if not is_positive_id(value):
        raise ToolError(f"{name} must be a positive integer, got {value!r}")
    return value


def _validate_limit(value: int) -> int:
    if value < 1 or value > 100:
        raise ToolError(f"limit must be between 1 and 100, got {value}")
    return value


def _envelope(
    rows: list[dict[str, Any]],
    *,
    cap: int | None = None,
    offset: int = 0,
) -> Envelope:
    """Wrap rows, preserving the legacy shape unless paging is requested."""
    if cap is None:
        return {"count": len(rows), "rows": rows}
    total = len(rows)
    page = rows[offset:offset + cap]
    truncated = offset + len(page) < total
    result: Envelope = {
        "count": len(page),
        "rows": page,
        "total": total,
        "truncated": truncated,
    }
    if truncated:
        result["next_offset"] = offset + len(page)
    return result


def _identity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return rows


# MCP users often configure credentials in the Claude Desktop extension rather
# than a terminal, so MCP login hints name both routes.
_MCP_LOGIN_HINT = (
    "MCP: enter or correct the Garmin email and password in the Claude Desktop extension settings, "
    "then retry; if Garmin asks for a one-time code, submit it with submit_mfa_code (it completes "
    "only a login challenge pending in this server). Terminal: run garmin-cli login, then retry."
)
# Logging in again does not fix an unsafe or unusable Garmin home.
_LOCAL_CONFIG_HINT = (
    "Fix the Garmin home directory (GARMIN_HOME): it must be a real directory owned by this user, "
    "not reached through a symlink, holding a regular token file; garmin-cli doctor names the failing check."
)
_MFA_REJECTED_HINT = (
    "Retry the original tool call to have Garmin send a new code, then submit that code with submit_mfa_code."
)


def mcp_recovery_hint(
    error_code: str,
    *,
    local_config: bool = False,
    mfa_rejected: bool = False,
    retry_after_seconds: float | None = None,
) -> str:
    """Recovery hint for MCP callers (the manifest's error inventory uses it too)."""
    if local_config:
        hint = _LOCAL_CONFIG_HINT
    elif mfa_rejected:
        hint = _MFA_REJECTED_HINT
    elif error_code in ("AUTH_MISSING", "AUTH_FAILED"):
        hint = _MCP_LOGIN_HINT
    else:
        hint = error_contract(error_code)["recovery_hint"]
    if retry_after_seconds is not None and not hint.startswith("Wait"):
        hint = f"Wait {retry_after_seconds:g} seconds first. {hint}"
    return hint


def _error_text(exc: GarminCliError) -> str:
    """Serialize the stable Garmin error contract for MCP text channels."""
    contract = error_contract(exc.error_code)
    retry_after_seconds: float | None = exc.retry_after_seconds
    if retry_after_seconds is None and exc.error_code == "RATE_LIMITED":
        retry_after_seconds = _resolve_retry_delays()[0]
    contract["recovery_hint"] = mcp_recovery_hint(
        exc.error_code,
        local_config=exc.local_config,
        mfa_rejected=exc.mfa_rejected,
        retry_after_seconds=retry_after_seconds,
    )
    # MCP's ToolError is text-only in the bundled SDK. A JSON object in that
    # text channel preserves a stable machine-readable contract while keeping
    # the existing human-readable message available to older clients.
    return json.dumps({
        "error_code": exc.error_code,
        "category": contract["category"],
        "message": exc.error,
        "recovery_hint": contract["recovery_hint"],
        "retry_after_seconds": retry_after_seconds,
    }, sort_keys=True)


def _handle_error(exc: GarminCliError) -> ToolError:
    return ToolError(_error_text(exc))


def _authenticated[T](config: CliConfig, produce: Callable[[], T]) -> T:
    """Ensure auth, run ``produce``, and translate GarminCliError to ToolError.

    Centralizes the ``ensure_authenticated(config)`` -> fetch -> ``except
    GarminCliError: raise _handle_error(exc)`` pattern. ``produce`` runs inside
    the same ``try`` so upstream Garmin errors are translated consistently.
    """
    try:
        ensure_authenticated(config)
        return produce()
    except GarminCliError as exc:
        raise _handle_error(exc) from exc


def _run_tool(
    config: CliConfig,
    fetch: Callable[[], Any],
    serialize: Callable[[Any], list[dict[str, Any]]] = _identity_rows,
) -> Envelope:
    """Auth, fetch, serialize, and envelope a read tool's rows.

    Collapses the read tools' identical 4-step body. Input parsing/validation
    stays in the tool (it must raise ``ToolError`` directly); ``serialize``
    defaults to identity for endpoints already returning row dicts.
    """
    return _envelope(serialize(_authenticated(config, fetch)))


def _validation_envelope(errors: list[str]) -> Envelope:
    return _envelope([{"ok": False, "error_code": "INVALID_INPUT", "errors": list(errors)}])


# Only NOT_FOUND degrades to a per-section gap (the metric simply has no data
# for that window). Every other error -- auth, rate limiting, server/network,
# bad input, or any future/unknown code -- fails the whole snapshot, which
# would otherwise be silently partial and untrustworthy. An allowlist makes the
# safe direction (fail loudly) the default for codes not enumerated here.
_SNAPSHOT_RECOVERABLE_CODES: frozenset[str] = frozenset({"NOT_FOUND"})

# One report section: a stable name, a thunk that fetches raw upstream data,
# and a serializer that turns it into rows.
ReportSection = tuple[str, Callable[[], Any], Callable[[Any], list[dict[str, Any]]]]


def _fetch_section_rows(
    fetch: Callable[[], Any], serialize: Callable[[Any], list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    return serialize(fetch())


def _collect_report_sections(
    specs: list[ReportSection],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """Fan out a report's sections, isolating recoverable per-section gaps.

    Sections fetch concurrently on a bounded thread pool, but results are
    consumed in spec order so ``sections`` iterates deterministically. Returns
    ``(sections, unavailable)``. A section that raises a NOT_FOUND
    ``GarminCliError`` or returns no rows is recorded as an empty list and noted
    in ``unavailable`` with a ``reason`` (``not_found`` / ``no_data``). Any other
    ``GarminCliError`` propagates (first in spec order wins, after pending
    sections are cancelled and in-flight ones drained) so the caller's auth
    wrapper converts it to a ``ToolError`` and the whole snapshot fails loudly.
    """
    sections: dict[str, list[dict[str, Any]]] = {}
    unavailable: list[dict[str, str]] = []
    futures: list[Future[list[dict[str, Any]]]] = []
    with _bounded_thread_pool(len(specs)) as pool, _cancel_futures_on_error(futures):
        for _, fetch, serialize in specs:
            futures.append(pool.submit(_fetch_section_rows, fetch, serialize))
        for (name, _, _), future in zip(specs, futures, strict=True):
                try:
                    rows = future.result()
                except GarminCliError as exc:
                    if exc.error_code not in _SNAPSHOT_RECOVERABLE_CODES:
                        raise
                    sections[name] = []
                    unavailable.append({"section": name, "reason": exc.error_code.lower()})
                    continue
                sections[name] = rows
                if not rows:
                    unavailable.append({"section": name, "reason": "no_data"})
    return sections, unavailable
