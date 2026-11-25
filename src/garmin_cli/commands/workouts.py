"""Workout commands."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.commands._options import (
    OutputGroup,
    confirm_option,
    date_range_options,
    ensure_can_confirm,
    input_format_option,
    limit_option,
    reject_csv,
    require_confirmation,
    resolve_after_login,
    validate_limit,
)
from garmin_cli.date_utils import CLICK_DATE_TYPE, resolve_click_dates
from garmin_cli.endpoints._base import _validate_numeric_id
from garmin_cli.endpoints.workouts import (
    create_workout,
    delete_workout,
    get_calendar_range,
    get_workout,
    list_workouts,
    send_workout_to_device,
    unschedule_workout,
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
from garmin_cli.services.workouts import prepare_workout_send, schedule_workout_once
from garmin_cli.workout_builder import build_garmin_payload, merge_workout_payload
from garmin_cli.workout_schema import validate_workout_input

COLUMNS_WORKOUT_DELETE = ("id", "status")
COLUMNS_WORKOUT_SCHEDULE = ("workout_schedule_id", "date", "status")
COLUMNS_WORKOUT_UNSCHEDULE = ("id", "status")
COLUMNS_WORKOUT_SEND = ("workout_id", "workout_name", "device_id", "display_name", "status")

_dry_run_option = click.option(
    "--dry-run", is_flag=True, default=False,
    help="Validate and print the Garmin payload without saving anything.",
)
_stdin_option = click.option(
    "--stdin", "use_stdin", is_flag=True, default=False, help="Read the workout from stdin instead of FILE."
)
_DRY_RUN_CSV = "--dry-run prints a nested payload that CSV cannot hold; use --json."


def _echo_dry_run(ctx: click.Context, command: str, payload: dict[str, Any]) -> None:
    if ctx.obj["config"].output_format == "json":
        render_output("json", command, [{"dry_run": True, "wire_payload": payload}], ())
        return
    click.echo("Dry run: nothing was saved. Garmin payload:", err=True)
    click.echo(json.dumps(payload, indent=2))


@click.group(cls=OutputGroup)
def workout() -> None:
    """Workout commands."""


@workout.command("list")
@limit_option
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
@date_range_options(include_ahead=True)
@click.pass_context
def calendar_cmd(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    ahead: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get workout calendar for a date range (default: the next 7 days)."""
    if all(value is None for value in (value_date, date_from, date_to, days, ahead)):
        ahead = 7

    start, end = resolve_after_login(
        lambda: resolve_click_dates(value_date, days, ahead, date_from, date_to),
        lambda: ensure_authenticated(ctx.obj["config"]),
    )
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
@click.argument("file_path", required=False, metavar="[FILE]")
@_stdin_option
@input_format_option
@_dry_run_option
@click.pass_context
def create_cmd(
    ctx: click.Context,
    file_path: str | None,
    use_stdin: bool,
    input_format: str | None,
    dry_run: bool,
) -> None:
    """Create a new workout from a JSON or YAML file (or --stdin)."""
    if dry_run:
        reject_csv(ctx, _DRY_RUN_CSV)
    user_data = read_workout_input(file_path, use_stdin, input_format)
    errors = validate_workout_input(user_data)
    if errors:
        raise GarminCliError(error="; ".join(errors), error_code="INVALID_INPUT")
    garmin_payload = build_garmin_payload(user_data)
    if dry_run:
        _echo_dry_run(ctx, "workout create", garmin_payload)
        return
    ensure_authenticated(ctx.obj["config"])
    raw = create_workout(garmin_payload)
    if raw is None:
        raise GarminCliError(error="Workout creation returned no data.", error_code="SERVER_ERROR")
    data = serialize_workout_mutate(raw, "created")
    render_output(ctx.obj["config"].output_format, "workout create", data, COLUMNS_WORKOUT_MUTATE)


@workout.command("update")
@click.argument("workout_id")
@click.argument("file_path", required=False, metavar="[FILE]")
@_stdin_option
@input_format_option
@_dry_run_option
@click.pass_context
def update_cmd(
    ctx: click.Context,
    workout_id: str,
    file_path: str | None,
    use_stdin: bool,
    input_format: str | None,
    dry_run: bool,
) -> None:
    """Update an existing workout by ID (only the fields given change)."""
    if dry_run:
        reject_csv(ctx, _DRY_RUN_CSV)
    user_data = read_workout_input(file_path, use_stdin, input_format)
    errors = validate_workout_input(user_data, partial=True)
    if errors:
        raise GarminCliError(error="; ".join(errors), error_code="INVALID_INPUT")
    ensure_authenticated(ctx.obj["config"])
    existing = get_workout(workout_id)
    merged, warnings = merge_workout_payload(existing, user_data)
    for w in warnings:
        click.echo(f"WARNING: {w}", err=True)
    if dry_run:
        # The SDK forces workoutId to the path id before the PUT; show the same body.
        _echo_dry_run(ctx, "workout update", merged | {"workoutId": int(workout_id)})
        return
    update_workout(workout_id, merged)
    data = serialize_workout_mutate(merged, "updated")
    render_output(ctx.obj["config"].output_format, "workout update", data, COLUMNS_WORKOUT_MUTATE)


@workout.command("delete")
@click.argument("workout_id")
@confirm_option
@click.pass_context
def delete_cmd(ctx: click.Context, workout_id: str, confirm: bool) -> None:
    """Delete a workout by ID."""
    _validate_numeric_id(workout_id, "workout_id")  # before asking to confirm
    require_confirmation(ctx, confirm, f"Delete workout {workout_id}?")
    ensure_authenticated(ctx.obj["config"])
    delete_workout(workout_id)
    data: list[dict[str, Any]] = [{"id": workout_id, "status": "deleted"}]
    render_output(ctx.obj["config"].output_format, "workout delete", data, COLUMNS_WORKOUT_DELETE)


@workout.command("schedule")
@click.argument("workout_id")
@click.argument("schedule_date", metavar="DATE", type=CLICK_DATE_TYPE)
@click.option(
    "--allow-multiple", is_flag=True, default=False,
    help="Schedule even when the date already holds a different workout.",
)
@click.pass_context
def schedule_cmd(ctx: click.Context, workout_id: str, schedule_date: datetime, allow_multiple: bool) -> None:
    """Schedule a workout on a specific date (YYYY-MM-DD).

    Already scheduled there: reports status "no_op" without writing. A date
    holding a different workout is refused unless --allow-multiple. The
    schedule id may be empty when Garmin returns none.
    """
    validated_id = _validate_numeric_id(workout_id, "workout_id")
    ensure_authenticated(ctx.obj["config"])
    result = schedule_workout_once(validated_id, schedule_date.date(), allow_multiple=allow_multiple)
    data: list[dict[str, Any]] = [
        {
            "workout_schedule_id": result["workout_schedule_id"],
            "date": result["date"],
            "status": result["action"],
        }
    ]
    render_output(
        ctx.obj["config"].output_format,
        "workout schedule",
        data,
        COLUMNS_WORKOUT_SCHEDULE,
    )


@workout.command("send")
@click.argument("workout_id")
@click.option(
    "--device", "device_id", default=None, metavar="DEVICE_ID",
    help="Target device id (see `device list`); defaults to the only device that takes workouts of this sport.",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Resolve the target device and report it without sending anything.",
)
@confirm_option
@click.pass_context
def send_cmd(ctx: click.Context, workout_id: str, device_id: str | None, dry_run: bool, confirm: bool) -> None:
    """Send a saved workout to a watch or bike computer (delivered on its next sync)."""
    validated_id = _validate_numeric_id(workout_id, "workout_id")
    validated_device = None if device_id is None else _validate_numeric_id(device_id, "device_id")
    if not dry_run:
        ensure_can_confirm(ctx, confirm)  # scripts fail before login; a terminal is asked below
    ensure_authenticated(ctx.obj["config"])
    target = prepare_workout_send(validated_id, validated_device)
    if not dry_run:
        require_confirmation(
            ctx, confirm,
            f"Send workout {target['workout_name']} ({validated_id}) to "
            f"{target['display_name'] or 'unnamed device'} ({target['device_id']})?",
        )
        send_workout_to_device(validated_id, target["workout_name"], target["device_id"])
    data: list[dict[str, Any]] = [{**target, "status": "dry_run" if dry_run else "sent"}]
    render_output(ctx.obj["config"].output_format, "workout send", data, COLUMNS_WORKOUT_SEND)


@workout.command("unschedule")
@click.argument("schedule_id")
@confirm_option
@click.pass_context
def unschedule_cmd(ctx: click.Context, schedule_id: str, confirm: bool) -> None:
    """Remove a scheduled workout from the calendar (keeps the template).

    SCHEDULE_ID is the workout_schedule_id returned by `workout schedule`
    (also shown by `workout calendar`), not the workout ID.
    """
    _validate_numeric_id(schedule_id, "scheduled_workout_id")  # before asking to confirm
    require_confirmation(ctx, confirm, f"Unschedule workout schedule {schedule_id}?")
    ensure_authenticated(ctx.obj["config"])
    unschedule_workout(schedule_id)
    data: list[dict[str, Any]] = [{"id": schedule_id, "status": "unscheduled"}]
    render_output(
        ctx.obj["config"].output_format,
        "workout unschedule",
        data,
        COLUMNS_WORKOUT_UNSCHEDULE,
    )
