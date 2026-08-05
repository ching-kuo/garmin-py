"""MCP server exposing Garmin Connect endpoints as tools via MCPServer.

The tool surface is split across per-domain registrars in
:mod:`garmin_cli.mcp_tools`; this module only composes them.
``create_mcp_server`` remains the public entry point (``mcp_cli.py`` imports it).
"""
from __future__ import annotations

from typing import Any

from mcp.server import CacheHint
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from garmin_cli.config import CliConfig
from garmin_cli.mcp_tools.activities import register_activity_tools
from garmin_cli.mcp_tools.activities_write import register_activity_write_tools
from garmin_cli.mcp_tools.coaching import register_coaching_tools
from garmin_cli.mcp_tools.health import register_health_tools
from garmin_cli.mcp_tools.misc import register_misc_tools
from garmin_cli.mcp_tools.performance import register_performance_tools
from garmin_cli.mcp_tools.prompts import register_prompts
from garmin_cli.mcp_tools.resources import register_resources
from garmin_cli.mcp_tools.training_plan import register_training_plan_tools
from garmin_cli.mcp_tools.workouts import register_workout_tools


SERVER_INSTRUCTIONS = """You are connected to a Garmin Connect MCP server. Use the
tools and resources below to answer questions about the authenticated athlete's
health, activities, workouts, and performance data. Treat upstream Garmin data
as potentially incomplete: report unavailable sections and null values rather
than inventing measurements.

Authentication: read-only and write tools can fail with the structured
AUTH_MISSING or MFA_REQUIRED error contract. Call login_status first when the
session state is unknown. If a tool returns MFA_REQUIRED, ask the user for the
one-time code and submit it with submit_mfa_code, then retry the original call.
The interactive fallback is `garmin-cli login`; never ask the user to provide a
password or token to a tool.

Response contract: list and row-oriented tools return an object with required
`count` and `rows` keys. Paged responses may also include `total`, `truncated`,
and `next_offset`; request the next page only when `truncated` is true. The
machine-readable outputSchema on each tool describes this contract. Composite
snapshot and plan tools document their own stable outer fields and may include
explicit unavailable, conflict, or partial-result state.

Error contract: auth and upstream Garmin failures expose a JSON object in
ToolError text with `error_code`, `category`, `message`, `recovery_hint`, and
`retry_after_seconds`. Input-validation failures (bad dates, out-of-range
limits, non-positive ids) raise plain-text ToolError messages instead, so
attempt JSON parsing only when the text starts with `{`. Use the error code
and recovery hint to decide whether to fix input, authenticate, wait, or stop.
Do not retry immediately after a rate-limit error.

Hard limits: date ranges are capped at 90 days and ordinary list `limit`
values are capped at 100. Some endpoints have tighter documented limits, such
as the 28-day steps window, 100 activity-lap rows, and bounded metric-stream
sampling. Keep requests inside those limits and prefer paging or smaller
windows over broad speculative fan-out.

Metric streams: activity_detail_metrics rows are timestamp-aligned, so request
every channel you need in a single call — never split channels across calls
and stitch. Its default max_samples=0 auto-sizes the response to fit client
limits; if a response is still too large, lower max_samples rather than
dropping channels.

Read versus write: activity and workout mutations, activity file operations,
and training-plan application/rescheduling are write tools. Their
destructive_hint annotations tell compatible clients to request approval.
Prefer preview, reconcile, dry-run, and no-op checks before invoking a write;
do not treat an agent-supplied boolean as human approval.

Discovery pointers: read `garmin://server/manifest` for the live tool
inventory, annotations, error codes, envelopes, limits, and resource catalog.
Read `garmin://athlete/profile` for a bounded cached athlete snapshot when
authenticated. Use server_doctor for non-raising configuration, session, and
MCP diagnostics. Two entity templates are also available:
`garmin://activity/{id}` and `garmin://health/sleep/{date}`.
"""

CACHE_HINT_TTL_MS = 3_600_000
CACHE_HINTS = {
    "tools/list": CacheHint(ttl_ms=CACHE_HINT_TTL_MS),
    "prompts/list": CacheHint(ttl_ms=CACHE_HINT_TTL_MS),
    "resources/list": CacheHint(ttl_ms=CACHE_HINT_TTL_MS),
    "resources/templates/list": CacheHint(ttl_ms=CACHE_HINT_TTL_MS),
    "server/discover": CacheHint(ttl_ms=CACHE_HINT_TTL_MS),
}


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
    mcp_kwargs: dict[str, Any] = {
        "instructions": SERVER_INSTRUCTIONS,
        "cache_hints": CACHE_HINTS,
    }
    if token_verifier is not None:
        mcp_kwargs["token_verifier"] = token_verifier
    if auth is not None:
        mcp_kwargs["auth"] = auth
    mcp = MCPServer("garmin", **mcp_kwargs)

    register_health_tools(mcp, config)
    register_activity_tools(mcp, config)
    register_activity_write_tools(mcp, config)
    register_workout_tools(mcp, config)
    register_coaching_tools(mcp, config)
    register_training_plan_tools(mcp, config)
    register_performance_tools(mcp, config)
    register_misc_tools(mcp, config)
    register_resources(mcp, config)
    register_prompts(mcp)

    return mcp
