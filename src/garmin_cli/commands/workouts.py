"""Workout commands."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.commands._options import validate_limit
from garmin_cli.date_utils import CLICK_DATE_TYPE, resolve_date_range
from garmin_cli.endpoints.workouts import (
    create_workout,
    delete_workout,
    get_calendar_range,
    get_workout,
    list_workouts,
    schedule_workout,
    update_workout,
)
from garmin_cli.exceptions import GarminCliError
from garmin_cli.input_reader import read_workout_input
from garmin_cli.output import render_output
from garmin_cli.serializers import (
    COLUMNS_CALENDAR_WORKOUT,
    COLUMNS_WORKOUT,
    COLUMNS_WORKOUT_DETAIL,
    COLUMNS_WORKOUT_MUTATE,
    serialize_calendar_workout,
    serialize_workout_detail,
    serialize_workout_mutate,
    serialize_workout_summary,
)
from garmin_cli.workout_builder import build_garmin_payload, merge_workout_payload
from garmin_cli.workout_schema import validate_workout_input

COLUMNS_WORKOUT_DELETE = ("id", "status")
COLUMNS_WORKOUT_SCHEDULE = ("workoutScheduleId", "date", "status")


@click.group()
def workout() -> None:
    """Workout commands."""


@workout.command("list")
@click.option("--limit", type=int, default=20)
@click.pass_context
def list_cmd(ctx: click.Context, limit: int) -> None:
    """List workouts."""
    validate_limit(limit)
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
@click.option("--from", "date_from", type=CLICK_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=CLICK_DATE_TYPE, default=None)
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


@workout.command("create")
@click.argument("file_path", required=False, metavar="FILE")
@click.option("--stdin", "use_stdin", is_flag=True, default=False)
@click.option("--input-format", type=click.Choice(["json", "yaml"]), default=None)
@click.pass_context
def create_cmd(
    ctx: click.Context,
    file_path: str | None,
    use_stdin: bool,
    input_format: str | None,
) -> None:
    """Create a new workout from a JSON or YAML file."""
    ensure_authenticated(ctx.obj["config"])
    user_data = read_workout_input(file_path, use_stdin, input_format)
    errors = validate_workout_input(user_data)
    if errors:
        raise GarminCliError(error="; ".join(errors), error_code="INVALID_INPUT")
    garmin_payload = build_garmin_payload(user_data)
    raw = create_workout(garmin_payload)
    if raw is None:
        raise GarminCliError(error="Workout creation returned no data.", error_code="SERVER_ERROR")
    data = serialize_workout_mutate(raw, "created")
    render_output(ctx.obj["config"].output_format, "workout create", data, COLUMNS_WORKOUT_MUTATE)


@workout.command("update")
@click.argument("workout_id")
@click.argument("file_path", required=False, metavar="FILE")
@click.option("--stdin", "use_stdin", is_flag=True, default=False)
@click.option("--input-format", type=click.Choice(["json", "yaml"]), default=None)
@click.pass_context
def update_cmd(
    ctx: click.Context,
    workout_id: str,
    file_path: str | None,
    use_stdin: bool,
    input_format: str | None,
) -> None:
    """Update an existing workout by ID."""
    ensure_authenticated(ctx.obj["config"])
    user_data = read_workout_input(file_path, use_stdin, input_format)
    errors = validate_workout_input(user_data, partial=True)
    if errors:
        raise GarminCliError(error="; ".join(errors), error_code="INVALID_INPUT")
    existing = get_workout(workout_id)
    merged, warnings = merge_workout_payload(existing, user_data)
    for w in warnings:
        click.echo(f"WARNING: {w}", err=True)
    update_workout(workout_id, merged)
    data = serialize_workout_mutate(merged, "updated")
    render_output(ctx.obj["config"].output_format, "workout update", data, COLUMNS_WORKOUT_MUTATE)


@workout.command("delete")
@click.argument("workout_id")
@click.option("--confirm", is_flag=True, default=False)
@click.pass_context
def delete_cmd(ctx: click.Context, workout_id: str, confirm: bool) -> None:
    """Delete a workout by ID."""
    ensure_authenticated(ctx.obj["config"])
    if not confirm:
        click.confirm(f"Delete workout {workout_id}?", abort=True)
    delete_workout(workout_id)
    data: list[dict[str, Any]] = [{"id": workout_id, "status": "deleted"}]
    render_output(ctx.obj["config"].output_format, "workout delete", data, COLUMNS_WORKOUT_DELETE)


@workout.command("schedule")
@click.argument("workout_id")
@click.argument("schedule_date", metavar="DATE", type=CLICK_DATE_TYPE)
@click.pass_context
def schedule_cmd(ctx: click.Context, workout_id: str, schedule_date: datetime) -> None:
    """Schedule a workout on a specific date (YYYY-MM-DD)."""
    ensure_authenticated(ctx.obj["config"])
    raw = schedule_workout(workout_id, schedule_date.date())
    raw_dict = raw if isinstance(raw, dict) else {}
    data: list[dict[str, Any]] = [
        {
            "workoutScheduleId": raw_dict.get("workoutScheduleId"),
            "date": raw_dict.get("calendarDate"),
            "status": "scheduled",
        }
    ]
    render_output(
        ctx.obj["config"].output_format,
        "workout schedule",
        data,
        COLUMNS_WORKOUT_SCHEDULE,
    )
