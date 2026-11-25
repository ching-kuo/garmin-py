"""Activity write MCP tool tests: delete, rename, set-type.

Download and upload (the file-root confined tools) live in
test_activity_file_tools.py.
"""
from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config, _tool_annotations  # noqa: E402

_MODULE = "garmin_cli.mcp_tools.activities_write"


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
