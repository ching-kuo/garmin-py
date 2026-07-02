"""Shared helpers for the MCP tool tests (moved from test_mcp_server.py)."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from garmin_cli.config import CliConfig


def _config(**overrides: Any) -> CliConfig:
    defaults = {"email": "test@example.com", "password": "test_password", "garth_home": "/tmp/garth"}
    defaults.update(overrides)
    return CliConfig(**defaults)


def _call(mcp_server: Any, tool_name: str, args: dict[str, Any] | None = None) -> Any:
    """Call an MCP tool and parse the JSON text result."""
    result = asyncio.run(mcp_server.call_tool(tool_name, args or {}))
    # MCPServer may return (list[Content], dict) tuple or list[Content]
    if isinstance(result, tuple):
        content_list = result[0]
    else:
        content_list = result
    return json.loads(content_list[0].text)
