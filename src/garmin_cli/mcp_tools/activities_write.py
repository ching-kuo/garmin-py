"""Activity write MCP tools (download, upload, delete, rename, set-type).

Kept separate from the activity read tools so the write-audit surface (which
mirrors the workout write tools) stays isolated. The generic audit machinery
lives in :mod:`garmin_cli.mcp_tools._audit`; this module owns only its
``_emit_write_log`` sink and the per-tool registrations.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from garmin_cli.auth import ensure_authenticated
from garmin_cli.config import CliConfig
from garmin_cli.endpoints.activities import (
    delete_activity,
    download_activity,
    extension_for_format,
    set_activity_name,
    set_activity_type,
    upload_activity,
)
from garmin_cli.exceptions import GarminCliError
from garmin_cli.mcp_tools._audit import WriteLogEvent, _emit_audit, _write_audit
from garmin_cli.mcp_tools._shared import (
    StrictId,
    _envelope,
    _validate_positive_id,
    _validation_envelope,
)
from garmin_cli.mcp_tools._schemas import Envelope
from garmin_cli.serializers import serialize_activity_upload

_FILE_ROOT_ENV = "GARMIN_MCP_FILE_ROOT"
_DEFAULT_FILE_ROOT = "~/Downloads/garmin-py"
_UPLOAD_UNAVAILABLE = f"File not available under {_FILE_ROOT_ENV}"

# Module-level so tests can patch the sink per domain.
_emit_write_log = _emit_audit

# Keys of endpoints.activities._DOWNLOAD_FORMAT_MAP (drift-guarded by a test).
DownloadFormat = Literal["original", "tcx", "gpx", "kml", "csv"]


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


def _private_copy(path: Path, directory: Path) -> Path | None:
    """Copy ``path`` into ``directory`` through one no-follow open, keeping its name.

    The upload then never reopens the user's path by name, so a final-component
    symlink swapped in after :func:`_confine` is refused (ELOOP), and a FIFO
    neither blocks (O_NONBLOCK) nor passes the regular-file check. Returns None
    for anything that is not a regular file.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with open(os.open(path, flags), "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            return None
        copy = directory / path.name  # Garmin detects the format from the suffix
        with open(copy, "xb") as target:
            shutil.copyfileobj(source, target)
    return copy


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
        activity_id: StrictId,
        fmt: DownloadFormat = "original",
        output_path: str | None = None,
        overwrite: bool = False,
    ) -> Envelope:
        """Download an activity file (fmt original = FIT inside a ZIP) and report its path, never its bytes.

        Files stay inside GARMIN_MCP_FILE_ROOT (default ~/Downloads/garmin-py);
        output_path is relative to it (default activity_<id><ext>), and escapes,
        ``..`` or symlinks are rejected. An existing file is kept unless
        overwrite=true. Bad paths return ok=false, error_code INVALID_INPUT;
        success returns ok=true, action "downloaded", activity_id, format,
        path, size_bytes.
        """
        _validate_positive_id(activity_id, "activity_id")
        base = WriteLogEvent(
            tool="activity_download",
            outcome="success",
            activity_id=activity_id,
            fmt=fmt,
        )
        with _write_audit(base, _emit_write_log) as audit:
            target = _download_target(
                output_path or f"activity_{activity_id}{extension_for_format(fmt)}",
                overwrite,
            )
            if isinstance(target, str):
                audit.fail_validation(1)
                return _validation_envelope([target])

            ensure_authenticated(config)
            payload = download_activity(activity_id, fmt)
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
            return _envelope([{
                "ok": True,
                "action": "downloaded",
                "activity_id": activity_id,
                "format": fmt,
                "path": str(target),
                "size_bytes": len(payload),
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def activity_upload(file_path: str) -> Envelope:
        """Upload a FIT, GPX, or TCX file from inside GARMIN_MCP_FILE_ROOT (relative paths resolve there).

        Any unusable path returns ok=false, error_code INVALID_INPUT. Success
        returns ok=true, action "uploaded", status (``rejected`` when Garmin
        declines it, e.g. a duplicate), activity_id.
        """
        base = WriteLogEvent(
            tool="activity_upload",
            outcome="success",
            path_len=len(file_path) if isinstance(file_path, str) else None,
        )
        # mkdtemp is 0700 and is always removed, copy included.
        with _write_audit(base, _emit_write_log) as audit, tempfile.TemporaryDirectory(
            prefix="garmin-upload-"
        ) as scratch:
            try:
                path = _confine(_file_root(), file_path) if file_path else None
                copy = _private_copy(path, Path(scratch)) if path is not None else None
            except (OSError, RuntimeError, ValueError):  # incl. PermissionError, ELOOP, bad root
                copy = None
            if copy is None:
                # One message for every case so the tool is no path-existence oracle.
                audit.fail_validation(1)
                return _validation_envelope([_UPLOAD_UNAVAILABLE])

            ensure_authenticated(config)
            raw = upload_activity(str(copy))
            # The CLI row's "file" key is dropped: the MCP reply never echoes paths.
            upload = serialize_activity_upload(str(copy), raw)[0]
            activity_id, status = upload["activity_id"], upload["status"]
            if status == "rejected":
                audit.rejected(activity_id=activity_id)
            else:
                audit.success(activity_id=activity_id)
            return _envelope([{
                "ok": True,
                "action": "uploaded",
                "status": status,
                "activity_id": activity_id,
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def activity_delete(activity_id: StrictId) -> Envelope:
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
            return _envelope([{
                "ok": True,
                "action": "deleted",
                "activity_id": activity_id,
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def activity_rename(activity_id: StrictId, name: str) -> Envelope:
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
            return _envelope([{
                "ok": True,
                "action": "renamed",
                "activity_id": activity_id,
                "name": name,
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def activity_set_type(activity_id: StrictId, type_key: str) -> Envelope:
        """Set an activity's sport type from a Garmin typeKey (e.g. running), checked against Garmin's live type table before any write.

        An empty key returns ok=false, error_code INVALID_INPUT. Success
        returns ok=true, action "type-updated", activity_id, type.
        """
        _validate_positive_id(activity_id, "activity_id")
        key_norm = type_key.strip().lower() if isinstance(type_key, str) else ""
        base = WriteLogEvent(
            tool="activity_set_type",
            outcome="success",
            activity_id=activity_id,
            # Caller free text: only its length until Garmin accepts the key.
            type_key_len=len(key_norm),
        )
        with _write_audit(base, _emit_write_log) as audit:
            if not key_norm:
                audit.fail_validation(1)
                return _validation_envelope(["Activity type key must be non-empty."])

            ensure_authenticated(config)
            set_activity_type(activity_id, key_norm)
            audit.success(type_key=key_norm, type_key_len=None)
            return _envelope([{
                "ok": True,
                "action": "type-updated",
                "activity_id": activity_id,
                "type": key_norm,
            }])
