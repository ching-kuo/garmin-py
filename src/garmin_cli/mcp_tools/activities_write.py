"""Activity write MCP tools (download, upload, delete, rename, set-type).

Kept separate from the activity read tools so the write-audit surface (which
mirrors the workout write tools) stays isolated. The generic audit machinery
lives in :mod:`garmin_cli.mcp_tools._shared`; this module owns only its
``_emit_write_log`` sink and the per-tool registrations.
"""
from __future__ import annotations

import contextlib
import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from garmin_cli.auth import ensure_authenticated
from garmin_cli.config import CliConfig
from garmin_cli.endpoints.activities import (
    _DOWNLOAD_FORMAT_MAP,
    delete_activity,
    download_activity,
    extension_for_format,
    set_activity_name,
    set_activity_type,
    upload_activity,
)
from garmin_cli.exceptions import GarminCliError
from garmin_cli.mcp_tools._shared import (
    WriteLogEvent,
    _validate_positive_id,
    _validation_envelope,
    _write_envelope,
    _write_audit,
)
from garmin_cli.mcp_tools._schemas import WriteEnvelope

_logger = logging.getLogger(__name__)

_FILE_ROOT_ENV = "GARMIN_MCP_FILE_ROOT"
_DEFAULT_FILE_ROOT = "~/Downloads/garmin-py"
_UPLOAD_UNAVAILABLE = f"File not available under {_FILE_ROOT_ENV}"


def _emit_write_log(event: WriteLogEvent) -> None:
    _logger.info("activity_write", extra={"event": event.__dict__})


def _file_root() -> Path:
    """Directory the MCP file tools are confined to (env override, else default)."""
    raw = os.environ.get(_FILE_ROOT_ENV, "").strip()
    if not raw or "${" in raw:
        # Unset, or a launcher placeholder (e.g. mcpb's ${HOME}) left unexpanded.
        raw = _DEFAULT_FILE_ROOT
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise ValueError(f"{_FILE_ROOT_ENV} must be an absolute path")
    return root.resolve()


def _within_root(root: Path, raw: str) -> Path | None:
    """Lexical containment, no filesystem access (outside paths are never probed).

    Relative paths are taken under ``root``. Rejects ``..`` components, NUL
    bytes, unknown ``~user`` prefixes, ``root`` itself, and anything else
    outside ``root``.
    """
    if "\x00" in raw:
        return None
    try:
        candidate = root / Path(raw).expanduser()
    except RuntimeError:  # ~user that does not exist
        return None
    if ".." in candidate.parts or candidate == root or not candidate.is_relative_to(root):
        return None
    # Rebuild on the canonical root so a case-insensitive match (Windows) can't
    # validate one spelling and then do I/O on another.
    return root / candidate.relative_to(root)


def _has_symlink(root: Path, path: Path) -> bool:
    """True if any component of ``path`` below ``root`` is a symlink.

    Uses ``os.lstat`` per component (parents pointing inside the root count
    too) because ``Path.is_symlink``/``exists`` swallow ``PermissionError`` on
    Python 3.14+; here it propagates. Nothing past a missing component exists.
    """
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except (FileNotFoundError, NotADirectoryError):
            return False
        if stat.S_ISLNK(mode) or os.path.isjunction(current):  # Windows junctions
            return True
    return False


def _confine(root: Path, raw: str) -> Path | None:
    """``raw`` as a path inside ``root`` with no symlinked component, else None."""
    candidate = _within_root(root, raw)
    if candidate is None or _has_symlink(root, candidate):
        return None
    return candidate


def _download_target(raw: str, overwrite: bool) -> Path | str:
    """The validated download path inside the file root, or the error message.

    Lexical checks run first; the root is created (0700) only for an otherwise
    valid request, and every filesystem check happens before auth/download.
    """
    try:
        root = _file_root()
    except (OSError, RuntimeError, ValueError) as exc:
        return f"{_FILE_ROOT_ENV} is not a usable directory: {exc}"
    outside = (
        f"output_path must resolve inside {_FILE_ROOT_ENV} ({root}), "
        "below the root itself, without '..' or symlinks."
    )
    target = _within_root(root, raw)
    if target is None:
        return outside
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if _has_symlink(root, target):
            return outside
        if target.exists() and not overwrite:
            return f"Output file already exists: {target}. Set overwrite=true to replace."
        if not target.parent.is_dir():
            return f"Output directory does not exist: {target.parent}"
        if not os.access(target.parent, os.W_OK | os.X_OK):
            return f"Output directory is not writable: {target.parent}"
    except PermissionError as exc:
        return f"Permission denied under {_FILE_ROOT_ENV} ({root}): {exc}"
    except OSError as exc:
        return f"{_FILE_ROOT_ENV} ({root}) is not a writable directory: {exc}"
    return target


def _write_confined(target: Path, payload: bytes, *, overwrite: bool) -> None:
    """Write without following a symlinked target; overwrite atomically."""
    if not overwrite:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(target, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
        except BaseException:
            # We created it (O_EXCL), so a partial file is ours to remove.
            with contextlib.suppress(OSError):
                os.unlink(target)
            raise
        return
    if target.is_symlink():
        raise OSError(f"Refusing to overwrite symlink: {target}")
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".garmin-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def register_activity_write_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register the activity-domain write tools on ``mcp``."""

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
        )
    )
    def activity_download(
        activity_id: int,
        fmt: str = "original",
        output_path: str | None = None,
        overwrite: bool = False,
    ) -> WriteEnvelope:
        """Download an activity file to disk and report the written path.

        ``fmt`` is one of original (FIT inside a ZIP), tcx, gpx, kml, csv.
        Files are confined to the ``GARMIN_MCP_FILE_ROOT`` directory (default
        ``~/Downloads/garmin-py``, created 0700 on first use). ``output_path``
        is optional; a relative path is taken under that root, and paths that
        escape it, contain ``..``, or pass through a symlink are rejected. It defaults
        to ``activity_<id><ext>`` in the root. The raw file bytes are never
        returned in the response -- only the path, byte size, and format.
        Refuses to overwrite an existing file unless ``overwrite=True``.

        On invalid input (unknown format, path outside the root, existing
        file without overwrite, missing output directory) returns one row with
        ``ok: False, error_code: "INVALID_INPUT", errors: [...]``. On success
        returns ``ok: True, action: "downloaded", activity_id, format, path,
        size_bytes``.
        """
        _validate_positive_id(activity_id, "activity_id")
        fmt_norm = fmt.lower()
        base = WriteLogEvent(
            tool="activity_download",
            outcome="success",
            activity_id=activity_id,
            fmt=fmt_norm,
        )
        with _write_audit(base, _emit_write_log) as audit:
            # The default name needs a valid format, so check that first.
            target = (
                _download_target(
                    output_path or f"activity_{activity_id}{extension_for_format(fmt_norm)}",
                    overwrite,
                )
                if fmt_norm in _DOWNLOAD_FORMAT_MAP
                else f"Invalid format '{fmt}'. Allowed: {', '.join(sorted(_DOWNLOAD_FORMAT_MAP))}."
            )
            if isinstance(target, str):
                audit.fail_validation(1)
                return _validation_envelope([target])

            ensure_authenticated(config)
            payload = download_activity(activity_id, fmt_norm)
            try:
                _write_confined(target, payload, overwrite=overwrite)
            except OSError as exc:
                # Disk-level failure after validation (permissions, disk full,
                # target raced into a directory): classify so the write audit
                # still emits exactly one event and the MCP layer gets a
                # ToolError instead of a raw exception.
                raise GarminCliError(
                    error=f"Failed to write output file: {exc}",
                    error_code="INTERNAL_ERROR",
                ) from exc
            audit.success(path_len=len(str(target)), size_bytes=len(payload))
            return _write_envelope([{
                "ok": True,
                "action": "downloaded",
                "activity_id": activity_id,
                "format": fmt_norm,
                "path": str(target),
                "size_bytes": len(payload),
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def activity_upload(file_path: str) -> WriteEnvelope:
        """Upload an activity file (FIT, GPX, or TCX) to Garmin Connect.

        ``file_path`` must resolve inside ``GARMIN_MCP_FILE_ROOT`` (default
        ``~/Downloads/garmin-py``); a relative path is taken under that root.
        A missing file, a path outside the root, a symlink, or a non-file all
        return the same row: ``ok: False, error_code: "INVALID_INPUT"``. On
        success returns ``ok: True, action: "uploaded", status, activity_id``
        (``status`` is ``rejected`` when Garmin declines the import, e.g. a
        duplicate).
        """
        base = WriteLogEvent(
            tool="activity_upload",
            outcome="success",
            path_len=len(file_path) if isinstance(file_path, str) else None,
        )
        with _write_audit(base, _emit_write_log) as audit:
            try:
                path = _confine(_file_root(), file_path) if file_path else None
                if path is not None and not path.is_file():
                    path = None
            except (OSError, RuntimeError, ValueError):  # incl. PermissionError, bad root
                path = None
            if path is None:
                # One message for every case so the tool is no path-existence oracle.
                audit.fail_validation(1)
                return _validation_envelope([_UPLOAD_UNAVAILABLE])

            ensure_authenticated(config)
            raw = upload_activity(str(path))
            activity_id, status = _extract_upload_result(raw)
            audit.success(activity_id=activity_id)
            return _write_envelope([{
                "ok": True,
                "action": "uploaded",
                "status": status,
                "activity_id": activity_id,
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def activity_delete(activity_id: int) -> WriteEnvelope:
        """Delete an activity by ID.

        Destructive: the activity is permanently removed. Returns
        ``ok: True, action: "deleted", activity_id`` on success.
        """
        _validate_positive_id(activity_id, "activity_id")
        base = WriteLogEvent(
            tool="activity_delete", outcome="success", activity_id=activity_id
        )
        with _write_audit(base, _emit_write_log) as audit:
            ensure_authenticated(config)
            delete_activity(activity_id)
            audit.success()
            return _write_envelope([{
                "ok": True,
                "action": "deleted",
                "activity_id": activity_id,
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def activity_rename(activity_id: int, name: str) -> WriteEnvelope:
        """Rename an activity. The name must be non-empty.

        Destructive: the activity's stored title is replaced. On an empty name
        returns ``ok: False, error_code: "INVALID_INPUT"``. On success returns
        ``ok: True, action: "renamed", activity_id, name``.
        """
        _validate_positive_id(activity_id, "activity_id")
        base = WriteLogEvent(
            tool="activity_rename",
            outcome="success",
            activity_id=activity_id,
            name_len=len(name) if isinstance(name, str) else None,
        )
        with _write_audit(base, _emit_write_log) as audit:
            if not name or not name.strip():
                audit.fail_validation(1)
                return _validation_envelope(["Activity name must be non-empty."])

            ensure_authenticated(config)
            set_activity_name(activity_id, name)
            audit.success()
            return _write_envelope([{
                "ok": True,
                "action": "renamed",
                "activity_id": activity_id,
                "name": name,
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def activity_set_type(activity_id: int, type_key: str) -> WriteEnvelope:
        """Set an activity's sport type from a Garmin ``typeKey`` (e.g. running).

        The key is resolved against Garmin's live sport-type table, so any key
        the account recognizes is accepted; an unknown key is rejected as
        invalid input before any write.
        Destructive: the activity's sport classification is replaced. On an
        empty key returns ``ok: False, error_code: "INVALID_INPUT"``. On success
        returns ``ok: True, action: "type-updated", activity_id, type``.
        """
        _validate_positive_id(activity_id, "activity_id")
        key_norm = type_key.strip().lower() if isinstance(type_key, str) else ""
        base = WriteLogEvent(
            tool="activity_set_type",
            outcome="success",
            activity_id=activity_id,
            type_key=key_norm or None,
        )
        with _write_audit(base, _emit_write_log) as audit:
            if not key_norm:
                audit.fail_validation(1)
                return _validation_envelope(["Activity type key must be non-empty."])

            ensure_authenticated(config)
            set_activity_type(activity_id, key_norm)
            audit.success()
            return _write_envelope([{
                "ok": True,
                "action": "type-updated",
                "activity_id": activity_id,
                "type": key_norm,
            }])


def _extract_upload_result(raw: Any) -> tuple[Any, str]:
    """Pull ``(activity_id, status)`` from the variable upload response shape.

    Mirrors the extraction in ``serialize_activity_upload``: Garmin returns
    HTTP 200 even when it rejects an import, so a ``detailedImportResult`` with
    failures and no successes is reported as ``rejected``.
    """
    if not isinstance(raw, dict):
        return None, "uploaded"
    status = "uploaded"
    activity_id: Any = None
    detailed = raw.get("detailedImportResult")
    if isinstance(detailed, dict):
        successes = detailed.get("successes") or []
        failures = detailed.get("failures") or []
        if successes and isinstance(successes[0], dict):
            activity_id = successes[0].get("internalId")
        elif failures:
            status = "rejected"
    if activity_id is None and status != "rejected":
        activity_id = raw.get("activityId") or raw.get("activity_id")
    upstream_status = raw.get("status")
    if upstream_status:
        status = str(upstream_status)
    return activity_id, status
