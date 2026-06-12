"""Front-end-agnostic service layer shared by the CLI and MCP front-ends.

Modules here own the data-shaping logic that previously lived duplicated in
``garmin_cli.commands.*`` and ``garmin_cli.mcp_server``. They depend only on
the endpoint and serializer layers and are deliberately free of any
front-end concern (no Click, no MCP ``ToolError``, no envelope assembly).
"""
from __future__ import annotations
