"""Workout commands."""
from __future__ import annotations

from typing import Any

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.endpoints.workouts import (
    get_calendar_range,
    get_workout,
    list_workouts,
)
from garmin_cli.output import render_output
from garmin_cli.serializers import (
    COLUMNS_CALENDAR_WORKOUT,
    COLUMNS_WORKOUT_DETAIL,
    COLUMNS_WORKOUT,
    serialize_calendar_workout,
    serialize_workout_detail,
    serialize_workout_summary,
)


@click.group()
def workout() -> None:
    """Workout commands."""


@workout.command("list")
@click.option("--limit", type=int, default=20)
@click.pass_context
def list_cmd(ctx: click.Context, limit: int) -> None:
    """List workouts."""
    from garmin_cli.exceptions import GarminCliError

    if limit <= 0:
        raise GarminCliError(
            error="--limit must be greater than 0",
            error_code="INVALID_INPUT",
        )
    ensure_authenticated(ctx.obj["config"])
    raw = list_workouts(limit=limit)
    data = serialize_workout_summary(raw)
    render_output(ctx.obj["config"].output_format, "workout list", data, COLUMNS_WORKOUT)


@workout.command("get")
@click.argument("workout_id")
@click.pass_context
def get_cmd(ctx: click.Context, workout_id: str) -> None:
    """Get a single workout by ID."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_workout(workout_id)
    data = serialize_workout_detail(raw)
    render_output(ctx.obj["config"].output_format, "workout get", data, COLUMNS_WORKOUT_DETAIL)


@workout.command("calendar")
@click.option("--from", "date_from", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--to", "date_to", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--days", type=int, default=None)
@click.option("--ahead", type=int, default=None)
@click.pass_context
def calendar_cmd(
    ctx: click.Context,
    date_from: Any,
    date_to: Any,
    days: int | None,
    ahead: int | None,
) -> None:
    """Get workout calendar for a date range."""
    from garmin_cli.date_utils import resolve_date_range

    if all(value is None for value in (date_from, date_to, days, ahead)):
        ahead = 7

    start, end = resolve_date_range(
        None,
        date_from.date() if date_from else None,
        date_to.date() if date_to else None,
        days,
        ahead,
        default_days=7,
    )
    ensure_authenticated(ctx.obj["config"])
    raw = get_calendar_range(start, end)
    items = raw if isinstance(raw, list) else []
    data = serialize_calendar_workout({"calendarItems": items})
    render_output(
        ctx.obj["config"].output_format,
        "workout calendar",
        data,
        COLUMNS_CALENDAR_WORKOUT,
        date_range=(start, end),
    )
