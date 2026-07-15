"""Activity write MCP tools (download, upload, delete, rename, set-type).

Kept separate from the activity read tools so the write-audit surface (which
mirrors the workout write tools) stays isolated. The generic audit machinery
lives in :mod:`garmin_cli.mcp_tools._shared`; this module owns only its
``_emit_write_log`` sink and the per-tool registrations.
"""
from __future__ import annotations

import logging
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
    _envelope,
    _validate_positive_id,
    _validation_envelope,
    _write_audit,
)

_logger = logging.getLogger(__name__)


def _emit_write_log(event: WriteLogEvent) -> None:
    _logger.info("activity_write", extra={"event": event.__dict__})


def register_activity_write_tools(mcp: MCPServer, config: CliConfig) -> None:
    """Register the activity-domain write tools on ``mcp``."""

    @mcp.tool()
    def activity_download(
        activity_id: int,
        fmt: str = "original",
        output_path: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Download an activity file to disk and report the written path.

        ``fmt`` is one of original (FIT inside a ZIP), tcx, gpx, kml, csv.
        ``output_path`` defaults to ``activity_<id><ext>`` in the current
        directory. The raw file bytes are never returned in the response --
        only the path, byte size, and format. Refuses to overwrite an existing
        file unless ``overwrite=True``.

        On invalid input (unknown format, existing file without overwrite,
        missing output directory) returns one row with ``ok: False,
        error_code: "INVALID_INPUT", errors: [...]``. On success returns
        ``ok: True, action: "downloaded", activity_id, format, path,
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
            errors: list[str] = []
            if fmt_norm not in _DOWNLOAD_FORMAT_MAP:
                errors.append(
                    f"Invalid format '{fmt}'. Allowed: {', '.join(sorted(_DOWNLOAD_FORMAT_MAP))}."
                )
            target = (
                Path(output_path)
                if output_path
                else Path.cwd() / f"activity_{activity_id}{extension_for_format(fmt_norm)}"
            )
            if not errors and target.exists() and not overwrite:
                errors.append(
                    f"Output file already exists: {target}. Set overwrite=true to replace."
                )
            if not errors and not target.parent.is_dir():
                errors.append(f"Output directory does not exist: {target.parent}")
            if errors:
                audit.fail_validation(len(errors))
                return _validation_envelope(errors)

            ensure_authenticated(config)
            payload = download_activity(activity_id, fmt_norm)
            try:
                target.write_bytes(payload)
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
                "format": fmt_norm,
                "path": str(target),
                "size_bytes": len(payload),
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def activity_upload(file_path: str) -> dict[str, Any]:
        """Upload an activity file (FIT, GPX, or TCX) to Garmin Connect.

        On a missing file returns one row with ``ok: False, error_code:
        "INVALID_INPUT"``. On success returns ``ok: True, action: "uploaded",
        status, activity_id`` (``status`` is ``rejected`` when Garmin declines
        the import, e.g. a duplicate).
        """
        base = WriteLogEvent(
            tool="activity_upload",
            outcome="success",
            path_len=len(file_path) if isinstance(file_path, str) else None,
        )
        with _write_audit(base, _emit_write_log) as audit:
            if not file_path or not Path(file_path).is_file():
                audit.fail_validation(1)
                return _validation_envelope([f"File not found: {file_path}"])

            ensure_authenticated(config)
            raw = upload_activity(file_path)
            activity_id, status = _extract_upload_result(raw)
            audit.success(activity_id=activity_id)
            return _envelope([{
                "ok": True,
                "action": "uploaded",
                "status": status,
                "activity_id": activity_id,
            }])

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
    def activity_delete(activity_id: int) -> dict[str, Any]:
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
    def activity_rename(activity_id: int, name: str) -> dict[str, Any]:
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
    def activity_set_type(activity_id: int, type_key: str) -> dict[str, Any]:
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
            return _envelope([{
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
