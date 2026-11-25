"""Write-tool audit log: one JSON line per write-tool call on ``garmin_cli.audit``.

Shared by every write tool (workout create/schedule/update/delete/unschedule/send,
activity download/upload/delete/rename/set-type, training-plan apply and
reschedule, submit_mfa_code). Each domain module binds ``_emit_audit`` as its
module-level ``_emit_write_log`` (so tests patch it per domain) and passes it
into ``_write_audit``. Calls rejected before a tool body runs (schema or id
validation) are recorded by the server's ``call_tool`` via
:func:`record_rejected_call`, unless the call already logged (``CALL_AUDITED``).
"""
from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from garmin_cli.exceptions import GarminCliError
from garmin_cli.mcp_tools._shared import _handle_error

_audit_logger = logging.getLogger("garmin_cli.audit")

# Bound per tool call by the server to a one-item list; set to True once the
# call logged. Sync tools run on anyio worker threads with a copy of the
# context, which still holds this same list.
CALL_AUDITED: ContextVar[list[bool] | None] = ContextVar("garmin_call_audited", default=None)

# Operation states that mean a plan call wrote (or may have written) to Garmin.
_WRITE_STATES = frozenset({"applied", "verified", "compensated", "unknown"})


class _StderrHandler(logging.Handler):
    """Write each record to the current ``sys.stderr`` (stdout carries MCP stdio)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


def configure_audit_logging() -> None:
    """Log audit lines at INFO; add a private stderr handler only in an unconfigured process.

    Call before the SDK configures logging. A host that configured
    ``garmin_cli.audit`` itself is left alone; one that configured the root
    logger receives the lines through normal propagation.
    """
    if _audit_logger.handlers:
        return
    if _audit_logger.level == logging.NOTSET:
        _audit_logger.setLevel(logging.INFO)
    if logging.getLogger().handlers:
        return
    _audit_logger.addHandler(_StderrHandler())
    # The SDK's root handler would re-print (and line-wrap) each JSON line.
    _audit_logger.propagate = False


WriteOutcome = Literal[
    "success",
    "dry-run",
    "conflict",
    "rejected",
    "failed-validation",
    "failed-auth",
    "failed-upstream",
]

EmitWriteLog = Callable[["WriteLogEvent"], None]


@dataclass(frozen=True)
class WriteLogEvent:
    """Structured payload for a single write-tool invocation log line.

    Only metadata is captured: caller free text (names, descriptions, paths,
    type keys Garmin has not accepted, MFA codes) is reduced to a length or left
    out, so PII never lands in logs. Bearer tokens are never read into this struct.
    """

    tool: str
    outcome: WriteOutcome
    dry_run: bool | None = None
    workout_id: int | None = None
    activity_id: int | None = None
    schedule_id: int | None = None
    device_id: int | None = None
    errors_count: int | None = None
    name_len: int | None = None
    description_len: int | None = None
    fmt: str | None = None
    size_bytes: int | None = None
    path_len: int | None = None
    # Logged only once Garmin accepted the key; type_key_len otherwise.
    type_key: str | None = None
    type_key_len: int | None = None
    # Training-plan result state (complete, no_op, compensated, partial, unknown).
    plan_outcome: str | None = None


def _emit_audit(event: WriteLogEvent) -> None:
    """Log one write event as a single JSON object (unset fields omitted)."""
    fields = {key: value for key, value in asdict(event).items() if value is not None}
    _audit_logger.info(json.dumps(fields, sort_keys=True))


def _classify_garmin_error(exc: GarminCliError) -> WriteOutcome:
    if exc.error_code in ("AUTH_MISSING", "AUTH_FAILED", "MFA_REQUIRED"):
        return "failed-auth"
    if exc.error_code == "INVALID_INPUT":
        # Rejected input (e.g. unknown activity type key surfaced by the live
        # type lookup) is a validation failure, not a Garmin/transport fault.
        return "failed-validation"
    return "failed-upstream"


def _plan_outcome(result: dict[str, Any]) -> WriteOutcome:
    if result.get("outcome") in ("complete", "no_op"):
        return "success"
    wrote = any(op.get("state") in _WRITE_STATES for op in result.get("operations") or [])
    errors = result.get("errors") or []
    # Nothing written, and the only errors are the live recheck refusing the
    # plan (INVALID_INPUT, e.g. a destination that became occupied).
    if not wrote and (result.get("conflicts") or errors) and all(
        error.get("error_code") == "INVALID_INPUT" for error in errors
    ):
        return "conflict"
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
        flag = CALL_AUDITED.get()
        if flag is not None:
            flag[0] = True

    def set_base(self, **fields: Any) -> None:
        """Add metadata learned mid-call (e.g. a resolved id) to every later event."""
        self._base = replace(self._base, **fields)

    def fail_validation(self, errors_count: int) -> None:
        self._emit(outcome="failed-validation", errors_count=errors_count)

    def dry_run(self) -> None:
        self._emit(outcome="dry-run")

    def success(self, **overrides: Any) -> None:
        self._emit(outcome="success", **overrides)

    def rejected(self, **overrides: Any) -> None:
        """Garmin answered but declined the write (e.g. a duplicate upload)."""
        self._emit(outcome="rejected", **overrides)

    def plan_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Record a training-plan result: complete/no_op succeed, conflicts without writes are conflicts."""
        self._emit(
            outcome=_plan_outcome(result),
            plan_outcome=result.get("outcome"),
            errors_count=len(result.get("errors") or []) or None,
        )
        return result


@contextmanager
def _write_audit(base: WriteLogEvent, emit: EmitWriteLog) -> Iterator[_WriteAudit]:
    """Own the write-audit logging lifecycle for a single write tool.

    Yields a :class:`_WriteAudit` for terminal outcomes (validation failure,
    dry-run, success). If a :class:`GarminCliError` escapes the ``with`` body
    and no event has been recorded yet, the classified ``failed-auth`` /
    ``failed-upstream`` outcome is logged before the error is converted to the
    caller-facing :class:`ToolError` (same translation as the read tools). A
    local ``ToolError`` is logged as ``failed-validation`` and any other
    exception as ``failed-upstream``; both are re-raised as is.
    """
    audit = _WriteAudit(base, emit)
    try:
        yield audit
    except GarminCliError as exc:
        if not audit._done:
            audit._emit(outcome=_classify_garmin_error(exc))
        raise _handle_error(exc) from exc
    except ToolError:
        if not audit._done:
            audit._emit(outcome="failed-validation")
        raise
    except Exception:
        if not audit._done:
            audit._emit(outcome="failed-upstream")
        raise


def record_rejected_call(tool: str, exc: ToolError) -> None:
    """Log a write-tool call that failed before its audit context ran (tool and outcome only)."""
    outcome: WriteOutcome = "failed-upstream" if isinstance(exc, UnexpectedToolError) else "failed-validation"
    _emit_audit(WriteLogEvent(tool=tool, outcome=outcome))
