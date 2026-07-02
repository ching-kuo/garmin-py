"""Shared Click option decorators and helpers for garmin-cli commands."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.date_utils import CLICK_DATE_TYPE, resolve_click_dates
from garmin_cli.exceptions import GarminCliError
from garmin_cli.output import render_output

F = TypeVar("F", bound=Callable[..., Any])


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
        fn = click.option("--to", "date_to", type=CLICK_DATE_TYPE, default=None)(fn)
        fn = click.option("--from", "date_from", type=CLICK_DATE_TYPE, default=None)(fn)
        if include_ahead:
            fn = click.option("--ahead", type=int)(fn)
        fn = click.option("--days", type=int)(fn)
        fn = click.option("--date", "value_date", type=CLICK_DATE_TYPE, default=None)(fn)
        return fn  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]


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
    *,
    ahead: int | None = None,
) -> None:
    """Resolve a date range, authenticate, fetch, serialize, and render output.

    Shared by the health and performance range commands. ``ahead`` is only
    meaningful for commands that stack the ``--ahead`` option (health sleep);
    performance commands leave it ``None`` and behave identically to before.
    """
    start, end = resolve_click_dates(value_date, days, ahead, date_from, date_to)
    ensure_authenticated(ctx.obj["config"])
    data = serializer(getter(start, end))
    render_output(
        ctx.obj["config"].output_format,
        command_name,
        data,
        columns,
        date_range=(start, end),
    )


def validate_limit(limit: int) -> None:
    """Raise GarminCliError when *limit* is not a positive integer.

    This encapsulates the workout-list validation rule and can be called from
    any command that accepts ``--limit``.  The error message and error_code
    intentionally mirror the existing workout list command so that
    ``--json`` output keeps the same ``error_code`` field.
    """
    if limit <= 0:
        raise GarminCliError(
            error="--limit must be greater than 0",
            error_code="INVALID_INPUT",
        )
