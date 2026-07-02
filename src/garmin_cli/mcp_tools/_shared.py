"""Shared infrastructure for the per-domain MCP tool registrars.

Holds the input validation, envelope/error translation, auth wrapper, and the
multi-section report fan-out that every domain module builds on. ``ensure_
authenticated`` is bound here so read tools uniformly gate on
``garmin_cli.mcp_tools._shared.ensure_authenticated``; write tools call it
inline at their own module scope instead.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from datetime import date
from typing import Any, TypeVar

from mcp.server.mcpserver.exceptions import ToolError

from garmin_cli.auth import ensure_authenticated
from garmin_cli.config import CliConfig
from garmin_cli.endpoints._base import _bounded_thread_pool, _cancel_futures_on_error
from garmin_cli.exceptions import GarminCliError

_MAX_DAYS = 90

_T = TypeVar("_T")


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ToolError(f"Invalid date format for {name}: expected YYYY-MM-DD, got '{value}'") from exc


def _parse_date_range(start_date: str, end_date: str) -> tuple[date, date]:
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start > end:
        raise ToolError(f"start_date must be on or before end_date: {start} > {end}")
    span = (end - start).days + 1
    if span > _MAX_DAYS:
        raise ToolError(f"Date range cannot exceed {_MAX_DAYS} days (got {span} days)")
    return start, end


def _validate_positive_id(value: int, name: str) -> int:
    if value <= 0:
        raise ToolError(f"{name} must be a positive integer, got {value}")
    return value


def _validate_limit(value: int) -> int:
    if value < 1 or value > 100:
        raise ToolError(f"limit must be between 1 and 100, got {value}")
    return value


def _envelope(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"count": len(rows), "rows": rows}


def _identity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return rows


def _handle_error(exc: GarminCliError) -> ToolError:
    msg = exc.error
    if exc.error_code == "AUTH_MISSING":
        msg = f"{msg} Run `garmin-cli login` to authenticate interactively."
    return ToolError(msg)


def _authenticated(config: CliConfig, produce: Callable[[], _T]) -> _T:
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
) -> dict[str, Any]:
    """Auth, fetch, serialize, and envelope a read tool's rows.

    Collapses the read tools' identical 4-step body. Input parsing/validation
    stays in the tool (it must raise ``ToolError`` directly); ``serialize``
    defaults to identity for endpoints already returning row dicts.
    """
    return _envelope(serialize(_authenticated(config, fetch)))


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
