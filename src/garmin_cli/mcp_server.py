"""MCP server exposing Garmin Connect endpoints as tools via MCPServer.

The tool surface is split across per-domain registrars in
:mod:`garmin_cli.mcp_tools`; this module only composes them.
``create_mcp_server`` remains the public entry point (``mcp_cli.py`` imports it).
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.server import CacheHint
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, InputRequiredResult

from garmin_cli.config import CliConfig
from garmin_cli.mcp_tools._audit import CALL_AUDITED, configure_audit_logging, record_rejected_call
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


_INSTRUCTIONS = """You are connected to a Garmin Connect MCP server. Use the
tools and resources below to answer questions about the authenticated athlete's
health, activities, workouts, and performance data. Treat upstream Garmin data
as potentially incomplete: report unavailable sections and null values rather
than inventing measurements.

Authentication: read-only and write tools can fail with the structured
AUTH_MISSING or MFA_REQUIRED error contract. Call login_status first when the
session state is unknown. If a tool returns MFA_REQUIRED, ask the user for the
one-time code and submit it with submit_mfa_code, then retry the original call.
For AUTH_MISSING or AUTH_FAILED, relay the error's recovery_hint: Claude
Desktop users fix the extension's Garmin email and password settings, terminal
users run `garmin-cli login`, and an unusable Garmin home needs a local fix,
not a login. Never ask the user to provide a password or token to a tool.

Response contract: list and row-oriented tools return an object with required
`count` and `rows` keys. Paged responses may also include `total`, `truncated`,
and `next_offset`; request the next page only when `truncated` is true. Only
activity_get, activity_detail_metrics, login_status, and submit_mfa_code
publish typed outputSchema fields. Composite snapshot and plan tools document
their own outer fields, including unavailable, conflict, or partial state.
The health_* and performance_* range tools take start_date or days, with
end_date defaulting to today.

Error contract: the SDK prefixes every tool error with
"Error executing tool <name>: ". For auth and upstream failures a JSON object follows, with
`error_code`, `category`, `message`, `recovery_hint`, and
`retry_after_seconds`; parse from the first `{{`. Input-validation failures
are plain text after the prefix. Use the error code and recovery hint to decide
whether to fix input, authenticate, wait, or stop. Do not retry immediately
after a rate-limit error. A non-null `retry_after_seconds` on an AUTH_FAILED or
RATE_LIMITED login error means new Garmin logins are paused that long.

Hard limits: date ranges are capped at 90 days and ordinary list `limit`
values are capped at 100. Some endpoints have tighter documented limits, such
as 100 activity-lap rows and bounded metric-stream sampling. Keep requests
inside those limits and prefer paging or smaller windows over broad
speculative fan-out.

Metric streams: activity_detail_metrics rows are timestamp-aligned, so request
every channel you need in a single call — never split channels across calls
and stitch. Its default max_samples=0 auto-sizes the response to fit client
limits; if a response is still too large, lower max_samples rather than
dropping channels.

{write_guidance}

Discovery pointers: read `garmin://server/manifest` for the live tool
inventory, annotations, error codes, envelopes, limits, and resource catalog.
Read `garmin://athlete/profile` for a bounded cached athlete snapshot when
authenticated. Use server_doctor for non-raising configuration, session, and
MCP diagnostics. Two entity templates are also available:
`garmin://activity/{{id}}` and `garmin://health/sleep/{{date}}`.
"""

_WRITE_GUIDANCE = """Read versus write: activity and workout mutations, activity file operations,
and training-plan application/rescheduling are write tools. Their
destructive_hint annotations tell compatible clients to request approval.
Prefer preview, reconcile, dry-run, and no-op checks before invoking a write;
do not treat an agent-supplied boolean as human approval."""

READ_ONLY_GUIDANCE = """Read-only server: write tools are not registered, so do not offer to
create, change, schedule, upload, download, or delete anything. training_plan_preview
still shows what a plan would change; the user applies it elsewhere."""


def server_instructions(read_only: bool) -> str:
    """Connection-time instructions for the server's mode."""
    return _INSTRUCTIONS.format(write_guidance=READ_ONLY_GUIDANCE if read_only else _WRITE_GUIDANCE)


SERVER_INSTRUCTIONS = server_instructions(read_only=False)

# Every tool that writes to Garmin or the local disk. submit_mfa_code stays:
# read tools cannot work until a pending login is completed.
WRITE_TOOLS = (
    "workout_create",
    "workout_update",
    "workout_delete",
    "workout_schedule",
    "workout_unschedule",
    "activity_upload",
    "activity_delete",
    "activity_rename",
    "activity_set_type",
    "activity_download",
    "training_plan_apply",
    "training_plan_reschedule",
)

# Write tools plus submit_mfa_code: every call to one emits one audit line.
_AUDITED_TOOLS = frozenset({*WRITE_TOOLS, "submit_mfa_code"})


class _GarminMCPServer(MCPServer):
    """MCPServer that audits write-tool calls rejected before the tool body runs."""

    audited_tools: frozenset[str] = _AUDITED_TOOLS

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[Any, Any] | None = None
    ) -> CallToolResult | InputRequiredResult:
        audited = [False]
        token = CALL_AUDITED.set(audited)
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            if name in self.audited_tools and not audited[0]:
                record_rejected_call(name, exc)
            raise
        finally:
            CALL_AUDITED.reset(token)


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
    read_only: bool = False,
) -> MCPServer:
    """Create an MCPServer with Garmin Connect tools.

    Args:
        config: CLI configuration (session home, credentials, etc.)
            captured by closure so every tool call has access.
        token_verifier: Optional bearer-token verifier; when supplied along
            with ``auth`` the MCP SDK gates all tools on the HTTP
            transports. Stdio and unauthenticated loopback callers leave
            both as ``None``.
        auth: Optional auth settings; required by the SDK when
            ``token_verifier`` is set.
        read_only: Leave out every tool in ``WRITE_TOOLS``.
    """
    configure_audit_logging()  # before the SDK configures the root logger
    mcp_kwargs: dict[str, Any] = {
        "instructions": server_instructions(read_only),
        "cache_hints": CACHE_HINTS,
        # The SDK logs failed tool and resource calls with their error text
        # (caller arguments) at INFO; keep that off stderr.
        "log_level": "WARNING",
    }
    if token_verifier is not None:
        mcp_kwargs["token_verifier"] = token_verifier
    if auth is not None:
        mcp_kwargs["auth"] = auth
    mcp = _GarminMCPServer("garmin", **mcp_kwargs)
    sdk_logger = logging.getLogger("mcp.server.mcpserver.server")
    if sdk_logger.level == logging.NOTSET:
        sdk_logger.setLevel(logging.WARNING)

    register_health_tools(mcp, config)
    register_activity_tools(mcp, config)
    register_activity_write_tools(mcp, config)
    register_workout_tools(mcp, config)
    register_coaching_tools(mcp, config)
    register_training_plan_tools(mcp, config)
    register_performance_tools(mcp, config)
    register_misc_tools(mcp, config, read_only=read_only)
    register_resources(mcp, config)
    register_prompts(mcp, read_only=read_only)
    if read_only:
        for name in WRITE_TOOLS:
            mcp.remove_tool(name)
        # A call to a removed tool fails as unknown and is not a write.
        mcp.audited_tools = _AUDITED_TOOLS - set(WRITE_TOOLS)
    # shortcut: reads the SDK's private tool registry (mcp<3 pinned); a test
    # fails if it moves. Generated titles ("Start Date") cost tokens on every
    # tools/list without telling a model anything the property name does not.
    for tool in mcp._tool_manager.list_tools():
        _drop_titles(tool.parameters)
        _drop_titles(tool.output_schema)

    return mcp


def _drop_titles(schema: Any) -> None:
    """Remove generated ``title`` strings in place (a property named title is a dict and stays)."""
    if isinstance(schema, dict):
        if isinstance(schema.get("title"), str):
            del schema["title"]
        for value in schema.values():
            _drop_titles(value)
    elif isinstance(schema, list):
        for value in schema:
            _drop_titles(value)
