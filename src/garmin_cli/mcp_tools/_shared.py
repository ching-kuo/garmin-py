"""Shared infrastructure for the per-domain MCP tool registrars.

Holds the input validation, envelope/error translation, auth wrapper, and the
multi-section report fan-out that every domain module builds on. ``ensure_
authenticated`` is bound here so read tools uniformly gate on
``garmin_cli.mcp_tools._shared.ensure_authenticated``; write tools call it
inline at their own module scope instead.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal, TypeVar

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


# --- Write-tool audit ------------------------------------------------------
#
# Shared by every write tool (workout create/schedule/update/delete, activity
# download/upload/delete/rename/set-type). Each domain module keeps its own
# module-level ``_emit_write_log`` (so tests patch it per domain and the log
# channel name stays domain-specific) and passes it into ``_write_audit``.

WriteOutcome = Literal[
    "success",
    "dry-run",
    "failed-validation",
    "failed-auth",
    "failed-upstream",
]

EmitWriteLog = Callable[["WriteLogEvent"], None]


@dataclass(frozen=True)
class WriteLogEvent:
    """Structured payload for a single write-tool invocation log line.

    Only metadata is captured -- free-text fields (workout/activity ``name``,
    ``description``, filesystem paths) are reduced to length-only integers so
    PII never lands in logs. Bearer tokens are never read into this struct.
    """

    tool: str
    outcome: WriteOutcome
    dry_run: bool = False
    workout_id: int | None = None
    activity_id: int | None = None
    errors_count: int | None = None
    name_len: int | None = None
    description_len: int | None = None
    fmt: str | None = None
    size_bytes: int | None = None
    path_len: int | None = None
    type_key: str | None = None


def _validation_envelope(errors: list[str]) -> dict[str, Any]:
    return _envelope(
        [{"ok": False, "error_code": "INVALID_INPUT", "errors": list(errors)}]
    )


def _classify_garmin_error(exc: GarminCliError) -> WriteOutcome:
    if exc.error_code in ("AUTH_MISSING", "AUTH_FAILED"):
        return "failed-auth"
    if exc.error_code == "INVALID_INPUT":
        # Rejected input (e.g. unknown activity type key surfaced by the live
        # type lookup) is a validation failure, not a Garmin/transport fault.
        return "failed-validation"
    return "failed-upstream"


class _WriteAudit:
    """Records exactly one structured log event for a write-tool invocation.

    Holds the invocation's invariant metadata as a base :class:`WriteLogEvent`;
    each terminal helper emits that base with the outcome (and any per-outcome
    field) filled in via the caller-supplied ``emit`` function. A single
    ``_done`` guard ensures one and only one log line per invocation.
    """

    def __init__(self, base: WriteLogEvent, emit: EmitWriteLog) -> None:
        self._base = base
        self._emit_fn = emit
        self._done = False

    def _emit(self, **overrides: Any) -> None:
        self._emit_fn(replace(self._base, **overrides))
        self._done = True

    def fail_validation(self, errors_count: int) -> None:
        self._emit(outcome="failed-validation", errors_count=errors_count)

    def dry_run(self) -> None:
        self._emit(outcome="dry-run")

    def success(self, **overrides: Any) -> None:
        self._emit(outcome="success", **overrides)


@contextmanager
def _write_audit(base: WriteLogEvent, emit: EmitWriteLog) -> Iterator[_WriteAudit]:
    """Own the write-audit logging lifecycle for a single write tool.

    Yields a :class:`_WriteAudit` for terminal outcomes (validation failure,
    dry-run, success). If a :class:`GarminCliError` escapes the ``with`` body
    and no event has been recorded yet, the classified ``failed-auth`` /
    ``failed-upstream`` outcome is logged before the error is converted to the
    caller-facing :class:`ToolError` (same translation as the read tools).
    """
    audit = _WriteAudit(base, emit)
    try:
        yield audit
    except GarminCliError as exc:
        if not audit._done:
            audit._emit(outcome=_classify_garmin_error(exc))
        raise _handle_error(exc) from exc


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
