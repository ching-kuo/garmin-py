"""CLI entrypoint for garmin-cli."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import click

from garmin_cli import __version__
from garmin_cli.commands.activities import activity
from garmin_cli.commands.devices import device
from garmin_cli.commands.health import health
from garmin_cli.commands.login import login
from garmin_cli.commands.performance import performance
from garmin_cli.commands.workouts import workout
from garmin_cli.config import CliConfig, load_config
from garmin_cli.exceptions import GarminCliError
from garmin_cli.mcp_cli import mcp_server_cmd
from garmin_cli.output import echo_json, make_error_envelope

_GLOBAL_OPTIONS_WITH_VALUES = ("--format", "--garmin-home", "--garth-home")


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


class SafeGroup(click.Group):
    """Top-level group with centralized exception handling."""

    def main(  # type: ignore[override]
        self, args: Sequence[str] | None = None, prog_name: str | None = None, **extra: Any
    ) -> Any:
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
@click.option(
    "--garmin-home",
    "--garth-home",
    "garmin_home",
    type=str,
    default=None,
    help="Override Garmin session directory. --garth-home is deprecated.",
)
@click.pass_context
def cli(ctx: click.Context, json_output: bool, output_format: str, garmin_home: str | None) -> None:
    """garmin-cli."""
    config = load_config()
    resolved_format = "json" if json_output else output_format
    ctx.ensure_object(dict)
    ctx.obj["config"] = CliConfig(
        email=config.email,
        password=config.password,
        garth_home=garmin_home or config.garth_home,
        output_format=resolved_format,
    )


cli.add_command(health)
cli.add_command(activity)
cli.add_command(performance)
cli.add_command(workout)
cli.add_command(device)
cli.add_command(login)
cli.add_command(mcp_server_cmd)


def main() -> None:
    cli.main()
