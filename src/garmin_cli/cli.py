"""CLI entrypoint for garmin-cli."""
from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence
from typing import Any, NoReturn

import click

from garmin_cli import __version__
from garmin_cli.config import CliConfig, load_config
from garmin_cli.exceptions import GarminCliError
from garmin_cli.mcp_cli import mcp_server_cmd
from garmin_cli.output import echo_json, make_error_envelope

_GLOBAL_OPTIONS_WITH_VALUES = frozenset({"--format", "--garmin-home", "--garth-home"})

# Subcommand groups load on first use so `garmin --version` / `--help` never
# pay for the Garmin backend import chain (garminconnect -> requests ->
# curl_cffi). Each entry maps a command name to (module, attribute, help);
# the help text must mirror the command's docstring — tests/test_cli_lazy.py
# asserts they stay in sync.
_LAZY_SUBCOMMANDS: dict[str, tuple[str, str, str]] = {
    "activity": ("garmin_cli.commands.activities", "activity", "Activity commands."),
    "coach": ("garmin_cli.commands.coaching", "coach", "AI-coaching data commands."),
    "device": ("garmin_cli.commands.devices", "device", "Device commands."),
    "doctor": (
        "garmin_cli.commands.doctor",
        "doctor",
        "Diagnose configuration, authentication, and MCP readiness.",
    ),
    "health": ("garmin_cli.commands.health", "health", "Health data commands."),
    "login": (
        "garmin_cli.commands.login",
        "login",
        "Login to Garmin Connect and save session tokens to the Garmin home directory.",
    ),
    "performance": ("garmin_cli.commands.performance", "performance", "Performance commands."),
    "workout": ("garmin_cli.commands.workouts", "workout", "Workout commands."),
}


def _command_name_from_args(args: Sequence[str] | None) -> str:
    # Only known command names are echoed, never raw argv tokens: an option
    # value (e.g. `login --password SECRET`) must not leak into the envelope.
    # Runs inside the error handler, so it never imports a lazy group: an
    # unloaded group reports just its bare name. A subcommand counts only
    # directly after its group, so `login --password status` stays "login".
    tokens = list(args or ())
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _GLOBAL_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if token not in _LAZY_SUBCOMMANDS and token not in cli.commands:
            return "garmin-cli"
        group = cli.commands.get(token)
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if isinstance(group, click.Group) and following in group.commands:
            return f"{token} {following}"
        return token
    return "garmin-cli"


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


def _fail(
    raw_args: Sequence[str], error: str, error_code: str, plain: str | None = None
) -> NoReturn:
    """Report an error as a JSON envelope (--json) or plain text, then exit 1."""
    if _json_requested(raw_args):
        echo_json(
            make_error_envelope(
                command=_command_name_from_args(raw_args),
                error=error,
                error_code=error_code,
            )
        )
    else:
        click.echo(error if plain is None else plain, err=True)
    raise SystemExit(1) from None


class SafeGroup(click.Group):
    """Top-level group with centralized exception handling and lazy subcommands."""

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(set(super().list_commands(ctx)) | set(_LAZY_SUBCOMMANDS))

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        command = super().get_command(ctx, cmd_name)
        if command is None and cmd_name in _LAZY_SUBCOMMANDS:
            module_name, attribute, _ = _LAZY_SUBCOMMANDS[cmd_name]
            command = getattr(importlib.import_module(module_name), attribute)
            self.add_command(command)
        return command

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        # Mirrors click.Group.format_commands, but takes not-yet-loaded
        # commands' help from _LAZY_SUBCOMMANDS instead of importing them.
        commands: list[tuple[str, click.Command]] = []
        for name in self.list_commands(ctx):
            command = self.commands.get(name)
            if command is None and name in _LAZY_SUBCOMMANDS:
                command = click.Command(name, help=_LAZY_SUBCOMMANDS[name][2])
            if command is None or command.hidden:
                continue
            commands.append((name, command))
        if not commands:
            return
        limit = formatter.width - 6 - max(len(name) for name, _ in commands)
        rows = [(name, command.get_short_help_str(limit)) for name, command in commands]
        with formatter.section("Commands"):
            formatter.write_dl(rows)

    def main(  # type: ignore[override]
        self, args: Sequence[str] | None = None, prog_name: str | None = None, **extra: Any
    ) -> Any:
        extra["standalone_mode"] = False
        # The console script calls main() bare. click still gets args=None (it
        # does its own argv handling, e.g. Windows wildcard expansion); the
        # JSON error handlers below need the raw argv to see --json.
        raw_args = sys.argv[1:] if args is None else args
        try:
            return super().main(args=args, prog_name=prog_name, **extra)
        except click.exceptions.Exit as exc:
            raise SystemExit(exc.exit_code) from None
        except GarminCliError as exc:
            _fail(raw_args, exc.error, exc.error_code)
        except click.ClickException as exc:  # incl. UsageError and startup refusals
            _fail(raw_args, str(exc), "INVALID_INPUT")
        except Exception as exc:
            _fail(raw_args, str(exc), "INTERNAL_ERROR", plain=f"Internal error: {exc}")


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


cli.add_command(mcp_server_cmd)


def main() -> None:
    cli.main()
