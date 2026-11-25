"""Shared Click option decorators and helpers for garmin-cli commands."""
from __future__ import annotations

import functools
import getpass
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any, TypeVar

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.config import PARSED_COMMAND, command_path
from garmin_cli.date_utils import CLICK_DATE_TYPE, resolve_click_dates
from garmin_cli.exceptions import GarminCliError
from garmin_cli.output import render_output

F = TypeVar("F", bound=Callable[..., Any])

MAX_LIMIT = 100
_LEAF_JSON = "garmin_cli.leaf_json"


def resolve_after_login[T](resolve: Callable[[], T], login: Callable[[], None]) -> T:
    """Resolve dates, log in, then resolve again.

    The first pass reports usage errors before any login; the second uses the
    profile-timezone today, which needs a session. Callers pass *login* so each
    command keeps its own ``ensure_authenticated`` seam.
    """
    resolve()
    login()
    return resolve()


def date_range_options(*, include_ahead: bool = False) -> Callable[[F], F]:
    """Decorator factory that stacks the standard date-range Click options.

    Stacks (in declaration order, so Click presents them top-to-bottom):
        --date    value_date   [%Y-%m-%d]  (default None)
        --days    days         INTEGER     (no default → None)
        --ahead   ahead        INTEGER     (no default → None)  — only when include_ahead=True
        --from    date_from    [%Y-%m-%d]  (default None)
        --to      date_to      [%Y-%m-%d]  (default None)

    The decorated function must accept the corresponding keyword arguments:
        value_date, days, [ahead,] date_from, date_to
    """

    def decorator(fn: F) -> F:
        # Apply options from bottom to top so --date appears first in --help.
        # Click stacks decorators in reverse order (last applied = first shown).
        fn = click.option(
            "--to", "date_to", type=CLICK_DATE_TYPE, default=None,
            help="Last date of the range (inclusive; use with --from).",
        )(fn)
        fn = click.option(
            "--from", "date_from", type=CLICK_DATE_TYPE, default=None,
            help="First date of the range (inclusive).",
        )(fn)
        if include_ahead:
            fn = click.option(
                "--ahead", type=int, help="The next N days starting today (1-90)."
            )(fn)
        fn = click.option(
            "--days", type=int, help="The last N days ending today (1-90)."
        )(fn)
        fn = click.option(
            "--date", "value_date", type=CLICK_DATE_TYPE, default=None,
            help="A single date (YYYY-MM-DD).",
        )(fn)
        return fn

    return decorator


def limit_option[Fn: Callable[..., Any]](fn: Fn) -> Fn:
    """The shared ``--limit`` option (validate with :func:`validate_limit`)."""
    return click.option(
        "--limit", type=int, default=20, show_default=True,
        help=f"Maximum number of results (1-{MAX_LIMIT}).",
    )(fn)


def confirm_option[Fn: Callable[..., Any]](fn: Fn) -> Fn:
    """The shared ``--confirm/--yes/-y`` flag for destructive commands."""
    return click.option(
        "--confirm", "--yes", "-y", "confirm", is_flag=True, default=False,
        help="Skip the confirmation prompt (required with --json or without a terminal).",
    )(fn)


def stdin_is_tty() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def prompt_line(prompt: str, *, hidden: bool = False) -> str:
    """Prompt on stderr and read one line from stdin (EOF raises click.Abort).

    Not click.prompt/confirm: they echo part of the prompt to stdout via input().
    """
    if hidden and sys.stdin.isatty():
        return getpass.getpass(f"{prompt}: ", stream=sys.stderr)
    sys.stderr.write(f"{prompt}: ")
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        raise click.Abort()
    return line.rstrip("\r\n")


def ensure_can_confirm(ctx: click.Context, confirmed: bool) -> None:
    """Fail early when a confirmation is needed but cannot be asked (``--json`` or no terminal)."""
    if not confirmed and (ctx.obj["config"].output_format == "json" or not stdin_is_tty()):
        raise GarminCliError(
            error="Confirmation required: pass --confirm (or --yes) with --json or without a terminal.",
            error_code="INVALID_INPUT",
        )


def require_confirmation(ctx: click.Context, confirmed: bool, prompt: str) -> None:
    """Ask *prompt* on stderr unless *confirmed*; never prompt for scripts.

    Under ``--json`` or without a terminal a prompt would corrupt output or
    hang, so the caller must pass ``--confirm``. Anything but y/yes (end of
    input included) is a decline: INVALID_INPUT "Aborted.".
    """
    if confirmed:
        return
    ensure_can_confirm(ctx, confirmed)
    try:
        answer = prompt_line(f"{prompt} [y/N]")
    except click.Abort:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        raise GarminCliError(error="Aborted.", error_code="INVALID_INPUT")


def reject_csv(ctx: click.Context, message: str) -> None:
    """Fail with INVALID_INPUT before any side effect when CSV cannot hold the output."""
    if ctx.obj["config"].output_format == "csv":
        raise GarminCliError(error=message, error_code="INVALID_INPUT")


def _set_output_format(ctx: click.Context, param: click.Parameter, value: Any) -> None:
    # Runs after the root group stored the global format, so the leaf wins.
    if not value:
        return
    if param.name == "json":
        ctx.meta[_LEAF_JSON] = ctx  # meta is shared by every context: mark this one
        value = "json"
    elif ctx.meta.get(_LEAF_JSON) is ctx:
        return  # --json beats --format at the same level, like the global options
    ctx.obj["config"] = replace(ctx.obj["config"], output_format=value)


def _mark_parsed[**P, R](callback: Callable[P, R]) -> Callable[P, R]:
    """Record, before the command body runs, that its options were parsed.

    Error reporting then trusts the parsed output format and command path
    instead of scanning argv.
    """

    @functools.wraps(callback)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        ctx = click.get_current_context()
        if ctx.invoked_subcommand is None:  # a group still has a subcommand to parse
            ctx.obj[PARSED_COMMAND] = command_path(ctx)
        return callback(*args, **kwargs)

    return wrapper


def output_options[C: click.Command](command: C) -> C:
    """Let *command* accept ``--json``/``--format`` after its name too (apply once)."""
    if command.callback is not None:
        command.callback = _mark_parsed(command.callback)
    command.params.extend([
        click.Option(
            ["--json"], is_flag=True, expose_value=False, callback=_set_output_format,
            help="Output JSON (same as the global --json).",
        ),
        click.Option(
            ["--format"],
            type=click.Choice(["table", "json", "csv"], case_sensitive=False),
            default=None, expose_value=False, callback=_set_output_format,
            help="Output format (overrides the global --format).",
        ),
    ])
    return command


class OutputGroup(click.Group):
    """Group whose leaf commands accept ``--json``/``--format`` after their name."""

    def add_command(self, cmd: click.Command, name: str | None = None) -> None:
        if not isinstance(cmd, click.Group):
            output_options(cmd)
        super().add_command(cmd, name)


def render_date_range(
    ctx: click.Context,
    command_name: str,
    getter: Callable[[Any, Any], Any],
    serializer: Callable[[Any], list[dict[str, Any]]],
    columns: tuple[str, ...],
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Resolve a date range, authenticate, fetch, serialize, and render output.

    Shared by the health and performance range commands.
    """
    start, end = resolve_after_login(
        lambda: resolve_click_dates(value_date, days, None, date_from, date_to),
        lambda: ensure_authenticated(ctx.obj["config"]),
    )
    data = serializer(getter(start, end))
    render_output(
        ctx.obj["config"].output_format,
        command_name,
        data,
        columns,
        date_range=(start, end),
    )


def validate_limit(limit: int) -> None:
    """Raise GarminCliError unless ``1 <= limit <= MAX_LIMIT``."""
    if not 1 <= limit <= MAX_LIMIT:
        raise GarminCliError(
            error=f"--limit must be between 1 and {MAX_LIMIT}",
            error_code="INVALID_INPUT",
        )
