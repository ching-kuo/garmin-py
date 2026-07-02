"""Activity write MCP tool tests: download, upload, delete, rename, set-type."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402

_MODULE = "garmin_cli.mcp_tools.activities_write"


def _tool_annotations(server: Any, tool_name: str) -> Any:
    tools = asyncio.run(server.list_tools())
    for t in tools:
        if t.name == tool_name:
            return t.annotations
    raise AssertionError(f"tool {tool_name!r} not registered")


class TestMcpActivityDownload:

    def test_writes_file_and_reports_path_not_bytes(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        download = mocker.patch(f"{_MODULE}.download_activity", return_value=b"FITDATA")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        target = tmp_path / "ride.gpx"
        server = create_mcp_server(_config())

        result = _call(
            server,
            "activity_download",
            {"activity_id": 12345, "fmt": "gpx", "output_path": str(target)},
        )
        row = result["rows"][0]
        assert row["ok"] is True
        assert row["action"] == "downloaded"
        assert row["path"] == str(target)
        assert row["size_bytes"] == len(b"FITDATA")
        assert row["format"] == "gpx"
        # Never leak raw bytes into the envelope.
        assert "bytes" not in row and "content" not in row
        assert target.read_bytes() == b"FITDATA"
        download.assert_called_once_with(12345, "gpx")
        event = log.call_args.args[0]
        assert event.tool == "activity_download"
        assert event.outcome == "success"
        assert event.size_bytes == len(b"FITDATA")
        assert event.path_len == len(str(target))

    def test_disk_write_failure_is_audited_tool_error(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        # A post-validation disk failure (target raced into a directory) must
        # still emit exactly one audit event and surface as ToolError, not a
        # raw OSError.
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        mocker.patch(f"{_MODULE}.download_activity", return_value=b"FITDATA")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        target = tmp_path / "ride.gpx"
        target.mkdir()
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Failed to write output file"):
            _call(
                server,
                "activity_download",
                {
                    "activity_id": 1,
                    "fmt": "gpx",
                    "output_path": str(target),
                    "overwrite": True,
                },
            )
        assert log.call_count == 1
        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"

    def test_refuses_overwrite_without_flag(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        download = mocker.patch(f"{_MODULE}.download_activity")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        existing = tmp_path / "ride.gpx"
        existing.write_bytes(b"old")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "activity_download",
            {"activity_id": 1, "fmt": "gpx", "output_path": str(existing)},
        )
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        assert any("already exists" in e for e in row["errors"])
        download.assert_not_called()
        assert existing.read_bytes() == b"old"
        event = log.call_args.args[0]
        assert event.outcome == "failed-validation"

    def test_overwrite_true_replaces(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        mocker.patch(f"{_MODULE}.download_activity", return_value=b"new")
        mocker.patch(f"{_MODULE}._emit_write_log")
        existing = tmp_path / "ride.gpx"
        existing.write_bytes(b"old")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "activity_download",
            {"activity_id": 1, "fmt": "gpx", "output_path": str(existing), "overwrite": True},
        )
        assert result["rows"][0]["ok"] is True
        assert existing.read_bytes() == b"new"

    def test_unknown_format_returns_validation_envelope(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        download = mocker.patch(f"{_MODULE}.download_activity")
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "activity_download",
            {"activity_id": 1, "fmt": "pdf", "output_path": str(tmp_path / "x.pdf")},
        )
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        download.assert_not_called()

    def test_missing_output_dir_returns_validation_envelope(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        download = mocker.patch(f"{_MODULE}.download_activity")
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "activity_download",
            {"activity_id": 1, "fmt": "gpx", "output_path": str(tmp_path / "nope" / "x.gpx")},
        )
        row = result["rows"][0]
        assert row["ok"] is False
        assert any("directory does not exist" in e for e in row["errors"])
        download.assert_not_called()

    def test_invalid_activity_id(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_download", {"activity_id": 0})

    def test_not_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "activity_download")
        # Writing a local file is not a destructive Garmin mutation.
        assert ann is None or ann.destructive_hint is not True


class TestMcpActivityUpload:

    def test_happy_path_reports_activity_id(self, mocker: Any, tmp_path: Path) -> None:
        f = tmp_path / "ride.fit"
        f.write_bytes(b"fit")
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        upload = mocker.patch(
            f"{_MODULE}.upload_activity",
            return_value={"detailedImportResult": {"successes": [{"internalId": 99}]}},
        )
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_upload", {"file_path": str(f)})
        row = result["rows"][0]
        assert row == {"ok": True, "action": "uploaded", "status": "uploaded", "activity_id": 99}
        upload.assert_called_once_with(str(f))
        event = log.call_args.args[0]
        assert event.tool == "activity_upload"
        assert event.outcome == "success"
        assert event.activity_id == 99
        # Path reduced to length only -- no PII in logs.
        assert event.path_len == len(str(f))

    def test_missing_file_returns_validation_envelope(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        upload = mocker.patch(f"{_MODULE}.upload_activity")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_upload", {"file_path": str(tmp_path / "nope.fit")})
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        upload.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "failed-validation"

    def test_rejected_import_reports_rejected(self, mocker: Any, tmp_path: Path) -> None:
        f = tmp_path / "dup.fit"
        f.write_bytes(b"fit")
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        mocker.patch(
            f"{_MODULE}.upload_activity",
            return_value={"detailedImportResult": {"successes": [], "failures": [{"m": "dup"}]}},
        )
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_upload", {"file_path": str(f)})
        row = result["rows"][0]
        assert row["ok"] is True
        assert row["status"] == "rejected"
        assert row["activity_id"] is None

    def test_upstream_failure(self, mocker: Any, tmp_path: Path) -> None:
        f = tmp_path / "ride.fit"
        f.write_bytes(b"fit")
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        mocker.patch(
            f"{_MODULE}.upload_activity",
            side_effect=GarminCliError(error="Internal server error.", error_code="SERVER_ERROR"),
        )
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Internal server error"):
            _call(server, "activity_upload", {"file_path": str(f)})
        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"


class TestMcpActivityDelete:

    def test_happy_path(self, mocker: Any) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        delete = mocker.patch(f"{_MODULE}.delete_activity")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_delete", {"activity_id": 12345})
        row = result["rows"][0]
        assert row == {"ok": True, "action": "deleted", "activity_id": 12345}
        delete.assert_called_once_with(12345)
        event = log.call_args.args[0]
        assert event.tool == "activity_delete"
        assert event.outcome == "success"
        assert event.activity_id == 12345

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "activity_delete")
        assert ann is not None
        assert ann.destructive_hint is True

    def test_invalid_activity_id(self, mocker: Any) -> None:
        delete = mocker.patch(f"{_MODULE}.delete_activity")
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_delete", {"activity_id": -1})
        delete.assert_not_called()

    def test_auth_missing(self, mocker: Any) -> None:
        mocker.patch(
            f"{_MODULE}.ensure_authenticated",
            side_effect=GarminCliError(error="No usable saved session", error_code="AUTH_MISSING"),
        )
        delete = mocker.patch(f"{_MODULE}.delete_activity")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "activity_delete", {"activity_id": 1})
        delete.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "failed-auth"


class TestMcpActivityRename:

    def test_happy_path(self, mocker: Any) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        rename = mocker.patch(f"{_MODULE}.set_activity_name")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_rename", {"activity_id": 12345, "name": "Evening Ride"})
        row = result["rows"][0]
        assert row == {"ok": True, "action": "renamed", "activity_id": 12345, "name": "Evening Ride"}
        rename.assert_called_once_with(12345, "Evening Ride")
        event = log.call_args.args[0]
        assert event.tool == "activity_rename"
        assert event.outcome == "success"
        # Name reduced to length only in the audit log.
        assert event.name_len == len("Evening Ride")

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "activity_rename")
        assert ann is not None
        assert ann.destructive_hint is True

    @pytest.mark.parametrize("bad_name", ["", "   "])
    def test_empty_name_returns_validation_envelope(self, mocker: Any, bad_name: str) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        rename = mocker.patch(f"{_MODULE}.set_activity_name")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_rename", {"activity_id": 1, "name": bad_name})
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        rename.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "failed-validation"

    def test_invalid_activity_id(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_rename", {"activity_id": 0, "name": "x"})


class TestMcpActivitySetType:

    def test_happy_path_normalizes_key(self, mocker: Any) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        set_type = mocker.patch(f"{_MODULE}.set_activity_type")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_set_type", {"activity_id": 12345, "type_key": "Cycling"})
        row = result["rows"][0]
        assert row == {"ok": True, "action": "type-updated", "activity_id": 12345, "type": "cycling"}
        set_type.assert_called_once_with(12345, "cycling")
        event = log.call_args.args[0]
        assert event.tool == "activity_set_type"
        assert event.outcome == "success"
        assert event.type_key == "cycling"

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "activity_set_type")
        assert ann is not None
        assert ann.destructive_hint is True

    def test_blank_key_returns_validation_envelope(self, mocker: Any) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        set_type = mocker.patch(f"{_MODULE}.set_activity_type")
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_set_type", {"activity_id": 1, "type_key": "   "})
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        set_type.assert_not_called()

    def test_unknown_key_from_endpoint_is_validation_failure(self, mocker: Any) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        mocker.patch(
            f"{_MODULE}.set_activity_type",
            side_effect=GarminCliError(
                error="Unknown activity type key: 'quidditch'.", error_code="INVALID_INPUT"
            ),
        )
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Unknown activity type key"):
            _call(server, "activity_set_type", {"activity_id": 1, "type_key": "quidditch"})
        event = log.call_args.args[0]
        assert event.outcome == "failed-validation"

    def test_invalid_activity_id(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_set_type", {"activity_id": 0, "type_key": "running"})
