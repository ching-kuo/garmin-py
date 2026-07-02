"""MCP server exposing Garmin Connect endpoints as tools via MCPServer.

The tool surface is split across per-domain registrars in
:mod:`garmin_cli.mcp_tools`; this module only composes them.
``create_mcp_server`` remains the public entry point (``mcp_cli.py`` imports it).
"""
from __future__ import annotations

from typing import Any

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from garmin_cli.config import CliConfig
from garmin_cli.mcp_tools.activities import register_activity_tools
from garmin_cli.mcp_tools.activities_write import register_activity_write_tools
from garmin_cli.mcp_tools.health import register_health_tools
from garmin_cli.mcp_tools.misc import register_misc_tools
from garmin_cli.mcp_tools.performance import register_performance_tools
from garmin_cli.mcp_tools.workouts import register_workout_tools


def create_mcp_server(
    config: CliConfig,
    *,
    token_verifier: TokenVerifier | None = None,
    auth: AuthSettings | None = None,
) -> MCPServer:
    """Create an MCPServer with Garmin Connect tools.

    Args:
        config: CLI configuration (session home, credentials, etc.)
            captured by closure so every tool call has access.
        token_verifier: Optional bearer-token verifier; when supplied along
            with ``auth`` the MCP SDK gates all tools on non-loopback
            transports. Loopback / stdio callers should leave both as
            ``None``.
        auth: Optional auth settings; required by the SDK when
            ``token_verifier`` is set.
    """
    mcp_kwargs: dict[str, Any] = {}
    if token_verifier is not None:
        mcp_kwargs["token_verifier"] = token_verifier
    if auth is not None:
        mcp_kwargs["auth"] = auth
    mcp = MCPServer("garmin", **mcp_kwargs)

    register_health_tools(mcp, config)
    register_activity_tools(mcp, config)
    register_activity_write_tools(mcp, config)
    register_workout_tools(mcp, config)
    register_performance_tools(mcp, config)
    register_misc_tools(mcp, config)

    return mcp
