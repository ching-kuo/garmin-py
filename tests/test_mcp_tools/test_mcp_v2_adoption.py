"""Contract tests for the MCP v2 metadata and structured-output adoption."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.auth import SessionProbeResult  # noqa: E402
from garmin_cli.mcp_server import (  # noqa: E402
    CACHE_HINTS,
    CACHE_HINT_TTL_MS,
    SERVER_INSTRUCTIONS,
    create_mcp_server,
)
from tests.test_mcp_tools.support import _config  # noqa: E402


def _tool(server: Any, name: str) -> Any:
    for tool in asyncio.run(server.list_tools()):
        if tool.name == name:
            return tool
    raise AssertionError(f"tool {name!r} not registered")


def test_envelope_tools_advertise_machine_readable_paging_schema() -> None:
    server = create_mcp_server(_config())
    for name in (
        "health_sleep",
        "activity_list",
        "workout_list",
        "performance_thresholds",
        "device_list",
    ):
        schema = _tool(server, name).output_schema
        assert schema is not None
        assert set(schema["required"]) == {"count", "rows"}
        assert {"total", "truncated", "next_offset"} <= set(schema["properties"])


def test_locally_owned_result_schemas_are_precise() -> None:
    server = create_mcp_server(_config())
    assert set(_tool(server, "login_status").output_schema["required"]) == {
        "authenticated",
        "garmin_home",
    }
    assert set(_tool(server, "submit_mfa_code").output_schema["required"]) == {
        "authenticated",
        "garmin_home",
    }
    assert set(_tool(server, "activity_detail_metrics").output_schema["required"]) == {
        "count",
        "rows",
        "samples_total",
        "samples_returned",
        "stride",
    }


def test_every_registered_tool_has_annotations() -> None:
    server = create_mcp_server(_config())
    tools = asyncio.run(server.list_tools())
    assert tools
    assert all(tool.annotations is not None for tool in tools)


def test_server_instructions_and_cache_hints() -> None:
    server = create_mcp_server(_config())
    assert 300 <= len(SERVER_INSTRUCTIONS.split()) <= 500
    for identifier in (
        "submit_mfa_code",
        "garmin://server/manifest",
        "garmin://athlete/profile",
        "server_doctor",
        "error_code",
        "90 days",
    ):
        assert identifier in SERVER_INSTRUCTIONS

    hints = server._lowlevel_server.cache_hints
    assert set(hints) == set(CACHE_HINTS)
    assert "resources/read" not in hints
    assert all(hint.ttl_ms == CACHE_HINT_TTL_MS for hint in hints.values())
    assert all(hint.scope == "private" for hint in hints.values())


def test_login_status_structured_content_round_trips(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.mcp_tools.misc.probe_session_status",
        return_value=SessionProbeResult(
            authenticated=True,
            garmin_home="/tmp/garth",
            latency_ms=1.0,
            detail="valid",
        ),
    )
    server = create_mcp_server(_config())
    result = asyncio.run(server.call_tool("login_status", {}))
    assert result.structured_content == {
        "authenticated": True,
        "garmin_home": "/tmp/garth",
    }


def test_activity_download_structured_content_round_trips(
    mocker: Any,
    tmp_path: Path,
) -> None:
    module = "garmin_cli.mcp_tools.activities_write"
    mocker.patch(f"{module}.ensure_authenticated")
    mocker.patch(f"{module}.download_activity", return_value=b"FITDATA")
    mocker.patch(f"{module}._emit_write_log")
    target = tmp_path / "activity.gpx"
    server = create_mcp_server(_config())

    result = asyncio.run(
        server.call_tool(
            "activity_download",
            {"activity_id": 123, "fmt": "gpx", "output_path": str(target)},
        )
    )
    assert result.structured_content["count"] == 1
    assert result.structured_content["rows"][0]["ok"] is True


def test_activity_laps_paging_validates_both_optional_paths(mocker: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
    mocker.patch("garmin_cli.mcp_tools.activities.get_activity", return_value={})
    mocker.patch(
        "garmin_cli.mcp_tools.activities._fetch_laps_rows_for_activity",
        return_value=[{"id": value} for value in range(101)],
    )
    server = create_mcp_server(_config())

    first = asyncio.run(server.call_tool("activity_laps", {"activity_id": 1}))
    assert first.structured_content["next_offset"] == 100

    final = asyncio.run(
        server.call_tool("activity_laps", {"activity_id": 1, "offset": 100})
    )
    assert final.structured_content["count"] == 1
    assert "next_offset" not in json.loads(final.content[0].text)
