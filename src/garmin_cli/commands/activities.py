"""Activity commands."""
from __future__ import annotations

from datetime import datetime

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.date_utils import CLICK_DATE_TYPE, resolve_click_dates
from garmin_cli.endpoints.activities import (
    get_activity,
    get_activity_weather,
    get_multisport_children,
    is_multisport_parent,
    list_activities,
)
from garmin_cli.output import echo_csv, echo_json, echo_table, make_envelope, render_output
from garmin_cli.serializers import (
    COLUMNS_ACTIVITY_SUMMARY,
    COLUMNS_ACTIVITY_WEATHER,
    COLUMNS_MULTISPORT_CHILDREN,
    serialize_activity_summary,
    serialize_multisport_children,
)

_DATE_TYPE = CLICK_DATE_TYPE


@click.group()
def activity() -> None:
    """Activity commands."""


@activity.command("list")
@click.option("--limit", type=int, default=20)
@click.option("--type", "activity_type", type=str, default=None)
@click.option("--search", type=str, default=None)
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.option("--days", type=int, default=None)
@click.option("--from", "date_from", type=_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=_DATE_TYPE, default=None)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    limit: int,
    activity_type: str | None,
    search: str | None,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """List recent activities, optionally filtered by date range."""
    has_date_args = any(x is not None for x in (value_date, days, date_from, date_to))
    start_date = None
    end_date = None
    if has_date_args:
        start_date, end_date = resolve_click_dates(value_date, days, None, date_from, date_to)
    ensure_authenticated(ctx.obj["config"])
    raw = list_activities(
        limit=limit, start=0, activity_type=activity_type, search=search,
        start_date=start_date, end_date=end_date,
    )
    data = serialize_activity_summary(raw)
    date_range = (start_date, end_date) if start_date is not None else None
    render_output(
        ctx.obj["config"].output_format, "activity list", data, COLUMNS_ACTIVITY_SUMMARY,
        date_range=date_range,
    )


@activity.command("get")
@click.argument("activity_id")
@click.pass_context
def get_cmd(ctx: click.Context, activity_id: str) -> None:
    """Get a single activity by ID. For multisport activities, shows each child sport."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_activity(activity_id)
    fmt = ctx.obj["config"].output_format
    data = serialize_activity_summary(raw)

    child_data: list[dict] = []
    if is_multisport_parent(raw):
        children = get_multisport_children(raw)
        if children:
            child_data = serialize_multisport_children(children)

    if fmt == "json":
        envelope = make_envelope(command="activity get", data=data)
        if child_data:
            envelope["children"] = child_data
        echo_json(envelope)
    elif fmt == "table":
        echo_table(data, COLUMNS_ACTIVITY_SUMMARY)
        if child_data:
            click.echo("")
            click.echo("Child activities:")
            echo_table(child_data, COLUMNS_MULTISPORT_CHILDREN)
    else:
        if child_data:
            echo_csv(child_data, COLUMNS_MULTISPORT_CHILDREN)
        else:
            echo_csv(data, COLUMNS_ACTIVITY_SUMMARY)


@activity.command("weather")
@click.argument("activity_id")
@click.pass_context
def weather_cmd(ctx: click.Context, activity_id: str) -> None:
    """Get weather data for an activity."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_activity_weather(activity_id)
    data = [raw] if isinstance(raw, dict) else (raw or [])
    render_output(ctx.obj["config"].output_format, "activity weather", data, COLUMNS_ACTIVITY_WEATHER)
