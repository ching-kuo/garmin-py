"""Training-plan commands: the CLI side of the MCP training_plan_* tools."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.commands._options import (
    OutputGroup,
    confirm_option,
    date_range_options,
    input_format_option,
    reject_csv,
    require_confirmation,
    resolve_after_login,
)
from garmin_cli.date_utils import CLICK_DATE_TYPE, resolve_click_dates
from garmin_cli.endpoints._base import _validate_numeric_id
from garmin_cli.exceptions import GarminCliError
from garmin_cli.input_reader import read_workout_input
from garmin_cli.output import echo_table, render_output
from garmin_cli.services.plan_apply import apply_training_plan, calendar_with_projections, plan_dates
from garmin_cli.services.plan_reconcile import RECONCILE_MAX_DAYS, collect_reconciliation, validate_reconcile_inputs
from garmin_cli.services.plan_reschedule import reschedule_schedule
from garmin_cli.services.training_plan import preview_training_plan, validate_training_plan

COLUMNS_PLAN_OPERATION = (
    "entry_id", "action", "state", "date", "workout_id",
    "workout_schedule_id", "schedule_id", "source_schedule_id", "restored_schedule_id", "error_code",
)
COLUMNS_PLAN_RECONCILE = ("date", "state", "planned", "workout_id", "activity_id", "sport", "match", "targets")
_NESTED_CSV = "plan results are nested and cannot be rendered as CSV; use --json."

_file_argument = click.argument("file_path", metavar="FILE")


def _dates_to_strings(value: Any, path: tuple[int, ...] = (), done: dict[int, Any] | None = None) -> Any:
    """Turn YAML's date values (unquoted 2026-07-15) back into the strings the plan schema wants.

    Only exact ``date`` values change: datetimes, keys, bytes and sets stay
    as loaded so validation rejects them. A recursive alias is refused; a
    shared alias is converted once and stays shared (*done*, by id), so
    nested aliases cannot multiply the work.
    """
    if type(value) is date:
        return value.isoformat()
    if not isinstance(value, (dict, list)):
        return value
    done = {} if done is None else done
    if id(value) in done:
        return done[id(value)]
    if id(value) in path:
        raise GarminCliError(error="The plan contains a recursive YAML alias.", error_code="INVALID_INPUT")
    path = (*path, id(value))
    if isinstance(value, dict):
        converted: Any = {key: _dates_to_strings(item, path, done) for key, item in value.items()}
    else:
        converted = [_dates_to_strings(item, path, done) for item in value]
    done[id(value)] = converted
    return converted


def _read_plan(file_path: str, input_format: str | None) -> dict[str, Any]:
    """Load a plan from FILE ('-' for stdin) and validate it before any Garmin call."""
    use_stdin = file_path == "-"
    data = _dates_to_strings(read_workout_input(None if use_stdin else file_path, use_stdin, input_format))
    errors = validate_training_plan(data)
    if errors:
        raise GarminCliError(error="; ".join(errors), error_code="INVALID_INPUT")
    return data


def _echo_plan_result(ctx: click.Context, command: str, result: dict[str, Any]) -> None:
    """Print the full result (JSON) or its operations, conflicts and errors; exit 1 if incomplete."""
    if ctx.obj["config"].output_format == "json":
        render_output("json", command, [result], ())
    else:
        echo_table(result["operations"], COLUMNS_PLAN_OPERATION)
        for title, rows, columns in (
            ("Conflicts", result["conflicts"], ("entry_id", "schedule_id", "reason")),
            ("Errors", result["errors"], ("error_code", "message")),
        ):
            if rows:
                click.echo(f"\n{title}:")
                echo_table(rows, columns)
        outcome = f"outcome: {result['outcome']}  " if "outcome" in result else ""
        click.echo(f"\n{outcome}complete: {str(result['complete']).lower()}")
    if not result["complete"]:
        raise SystemExit(1)


def _preview(ctx: click.Context, command: str, data: dict[str, Any]) -> None:
    ensure_authenticated(ctx.obj["config"])
    start, end = plan_dates(data)
    _echo_plan_result(ctx, command, preview_training_plan(data, *calendar_with_projections(start, end)))


@click.group("plan", cls=OutputGroup)
def plan() -> None:
    """Training-plan preview, apply, reschedule, reconcile."""


@plan.command("preview")
@_file_argument
@input_format_option
@click.pass_context
def preview_cmd(ctx: click.Context, file_path: str, input_format: str | None) -> None:
    """Diff a plan against the live calendar without writing.

    FILE is a JSON or YAML plan (the MCP training_plan_preview input); '-'
    reads stdin. Exits 1 when the plan has conflicts.
    """
    reject_csv(ctx, _NESTED_CSV)
    _preview(ctx, "plan preview", _read_plan(file_path, input_format))


@plan.command("apply")
@_file_argument
@input_format_option
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Preview against the live calendar without writing (same as `plan preview`).",
)
@confirm_option
@click.pass_context
def apply_cmd(ctx: click.Context, file_path: str, input_format: str | None, dry_run: bool, confirm: bool) -> None:
    """Apply a plan to the Garmin calendar after live rechecks.

    FILE as for `plan preview`; a plan on stdin needs --confirm unless --dry-run.
    Reapplying is a no-op. On a failed write the writes of this run are
    rolled back and the result lists each operation's state; exits 1 unless
    the plan was fully applied.
    """
    reject_csv(ctx, _NESTED_CSV)
    if file_path == "-" and not (confirm or dry_run):
        # A terminal prompt would read the rest of the piped plan as the answer.
        raise GarminCliError(
            error="Confirmation required: pass --confirm (or --yes) when the plan is read from stdin.",
            error_code="INVALID_INPUT",
        )
    data = _read_plan(file_path, input_format)
    if dry_run:
        _preview(ctx, "plan apply", data)
        return
    require_confirmation(
        ctx, confirm,
        f"Apply plan {data['name']!r} ({len(data['entries'])} entries, "
        f"{len(data.get('removals', []))} removals) to Garmin Connect?",
    )
    ensure_authenticated(ctx.obj["config"])
    _echo_plan_result(ctx, "plan apply", apply_training_plan(data))


@plan.command("reschedule")
@click.option("--schedule-id", required=True, help="workout_schedule_id to move (see `workout calendar`).")
@click.option("--new-date", type=CLICK_DATE_TYPE, required=True, help="Destination date (YYYY-MM-DD).")
@click.option(
    "--expected-date", type=CLICK_DATE_TYPE, required=True,
    help="Date the schedule is on now; the move is refused if it changed.",
)
@confirm_option
@click.pass_context
def reschedule_cmd(
    ctx: click.Context, schedule_id: str, new_date: datetime, expected_date: datetime, confirm: bool
) -> None:
    """Move one scheduled workout to a new date.

    The destination is scheduled first, then the source removed. A
    destination holding a different workout is a destination_occupied
    conflict and nothing is written; exits 1 unless the move completed.
    """
    reject_csv(ctx, _NESTED_CSV)
    validated_id = _validate_numeric_id(schedule_id, "--schedule-id")
    source, destination = expected_date.date(), new_date.date()
    require_confirmation(ctx, confirm, f"Move workout schedule {validated_id} from {source} to {destination}?")
    ensure_authenticated(ctx.obj["config"])
    _echo_plan_result(ctx, "plan reschedule", reschedule_schedule(validated_id, destination, source.isoformat()))


def _reconcile_row(entry: dict[str, Any]) -> dict[str, Any]:
    planned = entry["planned"] or {}
    actual = entry["actual"] or {}
    return {
        "date": planned.get("date") or actual.get("date"),
        "state": entry["state"],
        "planned": planned.get("name"),
        "workout_id": planned.get("workout_id"),
        "activity_id": actual.get("activity_id"),
        "sport": actual.get("sport") or planned.get("sport"),
        "match": entry["match_method"],
        "targets": (entry.get("target_comparison") or {}).get("state"),
    }


@plan.command("reconcile")
@date_range_options(max_days=RECONCILE_MAX_DAYS)
@click.option(
    "--detail", type=click.Choice(["summary", "targets"]), default="summary", show_default=True,
    help="targets also compares each completed workout's steps with its targets (more Garmin calls).",
)
@click.option("--max-activities", type=int, default=50, show_default=True, help="Activities to examine (1-100).")
@click.pass_context
def reconcile_cmd(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
    detail: str,
    max_activities: int,
) -> None:
    """Match scheduled workouts with completed activities.

    Default range: the last 7 days; at most 28 days. --json returns the full
    result (planned, actual, data quality, provenance).
    """

    def resolve() -> tuple[date, date]:
        start, end = resolve_click_dates(
            value_date, days, None, date_from, date_to, default_days=7, max_days=RECONCILE_MAX_DAYS
        )
        try:
            validate_reconcile_inputs(start, end, max_activities, names=("--from", "--to", "--max-activities"))
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc  # INVALID_INPUT, as in `coach snapshot`
        return start, end

    start, end = resolve_after_login(resolve, lambda: ensure_authenticated(ctx.obj["config"]))
    result = collect_reconciliation(start, end, detail, max_activities)
    output_format = ctx.obj["config"].output_format
    if output_format == "json":
        render_output("json", "plan reconcile", [result], (), date_range=(start, end))
        return
    if result["provenance"].get("truncated"):
        click.echo(
            f"Warning: only the first {max_activities} activities were examined; "
            "raise --max-activities to cover the whole range.",
            err=True,
        )
    rows = [_reconcile_row(entry) for entry in result["entries"]]
    render_output(output_format, "plan reconcile", rows, COLUMNS_PLAN_RECONCILE)
