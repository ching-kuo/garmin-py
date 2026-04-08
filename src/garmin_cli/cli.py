"""CLI entrypoint for garmin-cli."""
from __future__ import annotations

from collections.abc import Sequence
import inspect
from typing import Any

import click
from click.testing import CliRunner

from garmin_cli import __version__
from garmin_cli.commands.activities import activity
from garmin_cli.commands.health import health
from garmin_cli.commands.login import login
from garmin_cli.commands.performance import performance
from garmin_cli.commands.workouts import workout
from garmin_cli.config import CliConfig, load_config
from garmin_cli.exceptions import GarminCliError
from garmin_cli.output import echo_json, make_error_envelope

_GLOBAL_OPTIONS_WITH_VALUES = ("--format", "--garth-home")
_MCP_SERVER_TRANSPORTS = ("stdio", "sse", "streamable-http")


if "mix_stderr" not in inspect.signature(CliRunner.__init__).parameters:
    _cli_runner_init = CliRunner.__init__

    def _compat_cli_runner_init(self: CliRunner, *args: Any, mix_stderr: bool | None = None, **kwargs: Any) -> None:
        _ = mix_stderr
        _cli_runner_init(self, *args, **kwargs)

    CliRunner.__init__ = _compat_cli_runner_init


def _command_name_from_args(args: Sequence[str] | None) -> str:
    if not args:
        return "garmin-cli"
    parts: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in _GLOBAL_OPTIONS_WITH_VALUES:
            skip_next = True
            continue
        if any(arg.startswith(f"{option}=") for option in _GLOBAL_OPTIONS_WITH_VALUES):
            continue
        if arg.startswith("-"):
            continue
        parts.append(arg)
    return " ".join(parts[:2]) if parts else "garmin-cli"


def _json_requested(args: Sequence[str] | None) -> bool:
    if not args:
        return False
    for index, arg in enumerate(args):
        if arg == "--json":
            return True
        if arg == "--format" and index + 1 < len(args) and args[index + 1].lower() == "json":
            return True
        if arg.startswith("--format=") and arg.split("=", 1)[1].lower() == "json":
            return True
    return False


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


class SafeGroup(click.Group):
    """Top-level group with centralized exception handling."""

    def main(self, args: Sequence[str] | None = None, prog_name: str | None = None, **extra: Any) -> Any:
        extra["standalone_mode"] = False
        try:
            return super().main(args=args, prog_name=prog_name, **extra)
        except click.exceptions.Exit as exc:
            raise SystemExit(exc.exit_code) from None
        except GarminCliError as exc:
            if _json_requested(args):
                echo_json(
                    make_error_envelope(
                        command=_command_name_from_args(args),
                        error=exc.error,
                        error_code=exc.error_code,
                    )
                )
            else:
                click.echo(exc.error, err=True)
            raise SystemExit(1) from None
        except click.UsageError as exc:
            if _json_requested(args):
                echo_json(
                    make_error_envelope(
                        command=_command_name_from_args(args),
                        error=str(exc),
                        error_code="INVALID_INPUT",
                    )
                )
            else:
                click.echo(str(exc), err=True)
            raise SystemExit(1) from None
        except Exception as exc:
            if _json_requested(args):
                echo_json(
                    make_error_envelope(
                        command=_command_name_from_args(args),
                        error=str(exc),
                        error_code="INTERNAL_ERROR",
                    )
                )
            else:
                click.echo(f"Internal error: {exc}", err=True)
            raise SystemExit(1) from None


@click.group(cls=SafeGroup)
@click.version_option(version=__version__)
@click.option("--json", "json_output", is_flag=True, is_eager=False, help="Output JSON.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "csv"], case_sensitive=False),
    default="table",
    show_default=True,
    help="Output format.",
)
@click.option("--garth-home", type=str, default=None, help="Override garth home directory.")
@click.pass_context
def cli(ctx: click.Context, json_output: bool, output_format: str, garth_home: str | None) -> None:
    """garmin-cli."""
    config = load_config()
    resolved_format = "json" if json_output else output_format
    ctx.ensure_object(dict)
    ctx.obj["config"] = CliConfig(
        email=config.email,
        password=config.password,
        garth_home=garth_home or config.garth_home,
        output_format=resolved_format,
    )


cli.add_command(health)
cli.add_command(activity)
cli.add_command(performance)
cli.add_command(workout)
cli.add_command(login)


@cli.command("mcp-server")
@click.option(
    "--transport",
    default="stdio",
    type=click.Choice(_MCP_SERVER_TRANSPORTS),
    show_default=True,
    help="MCP transport to serve.",
)
@click.option("--host", type=str, default=None, help="Bind host for HTTP transports.")
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
        click.echo(
            'MCP support not installed. Run: pip install "garmin-cli[mcp]"',
            err=True,
        )
        raise SystemExit(1)
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
    server = create_mcp_server(config)
    server.run(**run_kwargs)


def main() -> None:
    cli.main()
