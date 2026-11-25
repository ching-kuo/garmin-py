"""MCP server subcommand — transport plumbing extracted from cli.py."""
from __future__ import annotations

import os
from typing import Any

import click

from garmin_cli.bearer_token import BEARER_ENV, validate_bearer_token
from garmin_cli.exceptions import GarminCliError

_MCP_SERVER_TRANSPORTS = ("stdio", "sse", "streamable-http")
_MCP_DEFAULT_LOOPBACK_HOST = "127.0.0.1"
_MCP_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_MCP_INSTALL_HINT = 'pip install "garmin-py[mcp]"'


def _validate_http_path_option(value: str | None, option_name: str) -> str | None:
    if value is None:
        return None
    if not value.startswith("/"):
        raise click.UsageError(f"{option_name} must start with '/'")
    return value


def _reject_invalid_options(
    options: dict[str, Any], *, message: str
) -> None:
    invalid = [name for name, val in options.items() if val not in (None, False)]
    if invalid:
        raise click.UsageError(f"{message}: {', '.join(invalid)}")


def _build_mcp_run_kwargs(
    *,
    transport: str,
    host: str | None,
    port: int | None,
    mount_path: str | None,
    sse_path: str | None,
    message_path: str | None,
    streamable_http_path: str | None,
    stateless_http: bool,
    json_response: bool,
) -> dict[str, Any]:
    mount_path = _validate_http_path_option(mount_path, "--mount-path")
    sse_path = _validate_http_path_option(sse_path, "--sse-path")
    message_path = _validate_http_path_option(message_path, "--message-path")
    streamable_http_path = _validate_http_path_option(
        streamable_http_path,
        "--streamable-http-path",
    )

    if transport == "stdio":
        _reject_invalid_options(
            {
                "--host": host,
                "--port": port,
                "--mount-path": mount_path,
                "--sse-path": sse_path,
                "--message-path": message_path,
                "--streamable-http-path": streamable_http_path,
                "--stateless-http": stateless_http,
                "--json-response": json_response,
            },
            message="HTTP-only options cannot be used with stdio transport",
        )
        return {"transport": "stdio"}

    if mount_path is not None:
        raise click.UsageError(
            "--mount-path is not supported by MCP v2 direct execution. "
            "Mount the ASGI app yourself if you need a path prefix."
        )

    if transport == "sse":
        _reject_invalid_options(
            {
                "--streamable-http-path": streamable_http_path,
                "--stateless-http": stateless_http,
                "--json-response": json_response,
            },
            message="The following options are only supported with streamable-http transport",
        )
    elif transport == "streamable-http":
        _reject_invalid_options(
            {"--sse-path": sse_path, "--message-path": message_path},
            message="The following options are only supported with sse transport",
        )

    run_kwargs: dict[str, Any] = {"transport": transport}
    if host is not None:
        run_kwargs["host"] = host
    if port is not None:
        run_kwargs["port"] = port
    if transport == "sse":
        if sse_path is not None:
            run_kwargs["sse_path"] = sse_path
        if message_path is not None:
            run_kwargs["message_path"] = message_path
        return run_kwargs
    if streamable_http_path is not None:
        run_kwargs["streamable_http_path"] = streamable_http_path
    if stateless_http:
        run_kwargs["stateless_http"] = True
    if json_response:
        run_kwargs["json_response"] = True
    return run_kwargs


def _normalize_bind_host(host: str | None) -> str:
    """The one host value used for both the bind and the auth decision.

    None means the loopback default. Brackets are stripped only from a
    bracketed IPv6 literal (``[::1]``); empty, whitespace-only, or other
    bracketed values are rejected, because an empty host would make the HTTP
    server bind every interface while the auth check saw no host at all.
    """
    if host is None:
        return _MCP_DEFAULT_LOOPBACK_HOST
    value = host
    if value.startswith("[") and value.endswith("]") and ":" in value[1:-1]:
        value = value[1:-1]
    if not value.strip() or "[" in value or "]" in value:
        raise click.UsageError(f"Invalid --host value: {host!r}")
    return value


def _resolve_mcp_auth(host: str, port: int | None) -> tuple[Any, Any]:
    """Resolve the (token_verifier, auth_settings) pair for an HTTP bind.

    ``host`` comes from :func:`_normalize_bind_host`. The bearer token is
    enforced whenever ``GARMIN_MCP_BEARER_TOKEN`` is present, loopback
    included (a local reverse proxy or tunnel would otherwise expose the
    server). Only an absent variable leaves a loopback bind unauthenticated;
    non-loopback binds require it. A missing or invalid (blank, non-RFC 6750
    characters, or shorter than 32 characters) required token raises a
    ``click.ClickException`` to refuse start-up.

    The ``http://<host>:<port>`` URL fed into ``AuthSettings`` is a synthetic
    placeholder that the SDK requires for static-token mode; the scheme is
    fixed at ``http`` because TLS is expected to be terminated by a reverse
    proxy in front of the server.
    """
    raw_token = os.environ.get(BEARER_ENV)
    if host in _MCP_LOOPBACK_HOSTS and raw_token is None:
        return None, None

    try:
        token = validate_bearer_token(raw_token or "")
    except ValueError as exc:
        raise click.ClickException(
            f"Refusing to bind {host!r}: {exc}. "
            f"Set a valid {BEARER_ENV}, or bind to a loopback host (127.0.0.1) "
            "with it unset."
        ) from exc

    # mcp_server_cmd already imported the mcp-backed server, so these succeed.
    from mcp.server.auth.settings import AuthSettings

    from garmin_cli.mcp_auth import StaticBearerTokenVerifier

    verifier = StaticBearerTokenVerifier(token)
    resolved_port = port if port is not None else 8000
    url_host = f"[{host}]" if ":" in host else host  # IPv6 literal
    base_url = f"http://{url_host}:{resolved_port}"
    # pydantic coerces these str URLs to AnyHttpUrl at construction; mypy only
    # sees the strict annotation when the mcp SDK's types are resolvable.
    # The static token carries no audience claim, so resource validation stays
    # off; the token is only ever valid for this server anyway.
    auth = AuthSettings(
        issuer_url=base_url,  # type: ignore[arg-type]
        resource_server_url=base_url,  # type: ignore[arg-type]
        validate_token_resource=False,
    )
    return verifier, auth


@click.command("mcp-server")
@click.option(
    "--transport",
    default="stdio",
    type=click.Choice(_MCP_SERVER_TRANSPORTS),
    show_default=True,
    help="MCP transport to serve.",
)
@click.option(
    "--host",
    type=str,
    default=None,
    help=(
        "Bind host for HTTP transports. Defaults to 127.0.0.1 (loopback). "
        f"Non-loopback binds require {BEARER_ENV}; when set, it is "
        "enforced on loopback binds too."
    ),
)
@click.option(
    "--port",
    type=click.IntRange(1, 65535),
    default=None,
    help="Bind port for HTTP transports.",
)
@click.option(
    "--mount-path",
    type=str,
    default=None,
    help="Deprecated in MCP v2 direct execution; rejected if provided.",
)
@click.option(
    "--sse-path",
    type=str,
    default=None,
    help="SSE event path. Only valid with --transport sse.",
)
@click.option(
    "--message-path",
    type=str,
    default=None,
    help="SSE message POST path. Only valid with --transport sse.",
)
@click.option(
    "--streamable-http-path",
    type=str,
    default=None,
    help="Streamable HTTP path. Only valid with --transport streamable-http.",
)
@click.option(
    "--stateless-http",
    is_flag=True,
    help="Enable stateless mode for streamable-http transport.",
)
@click.option(
    "--json-response",
    is_flag=True,
    help="Return JSON HTTP responses when supported by streamable-http clients.",
)
@click.pass_context
def mcp_server_cmd(
    ctx: click.Context,
    transport: str,
    host: str | None,
    port: int | None,
    mount_path: str | None,
    sse_path: str | None,
    message_path: str | None,
    streamable_http_path: str | None,
    stateless_http: bool,
    json_response: bool,
) -> None:
    """Start the Garmin MCP server for Claude Code integration."""
    try:
        from garmin_cli.mcp_server import create_mcp_server
    except ImportError as exc:
        if "mcp" not in str(exc):
            raise
        # Raised through SafeGroup so --json gets the error envelope.
        raise GarminCliError(
            error=f"MCP support not installed. Run: {_MCP_INSTALL_HINT}",
            error_code="INTERNAL_ERROR",
        ) from exc
    token_verifier = auth_settings = None
    if transport != "stdio":
        # Normalized once so the bind and the auth decision use the same value.
        host = _normalize_bind_host(host)
        token_verifier, auth_settings = _resolve_mcp_auth(host, port)
    run_kwargs = _build_mcp_run_kwargs(
        transport=transport,
        host=host,
        port=port,
        mount_path=mount_path,
        sse_path=sse_path,
        message_path=message_path,
        streamable_http_path=streamable_http_path,
        stateless_http=stateless_http,
        json_response=json_response,
    )
    config = ctx.obj["config"]
    server = create_mcp_server(
        config,
        token_verifier=token_verifier,
        auth=auth_settings,
    )
    server.run(**run_kwargs)
