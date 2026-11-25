"""Coaching-oriented read commands."""

from __future__ import annotations

from typing import Any

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.commands._options import OutputGroup, reject_csv
from garmin_cli.date_utils import today
from garmin_cli.output import echo_table, render_output
from garmin_cli.services.coaching_snapshot import collect_snapshot, validate_snapshot_inputs


@click.group("coach", cls=OutputGroup)
def coach() -> None:
    """AI-coaching data commands."""


@coach.command("snapshot")
@click.option(
    "--date", "as_of", type=click.DateTime(formats=["%Y-%m-%d"]), default=None,
    help="Snapshot day (default: today).",
)
@click.option("--baseline-days", type=int, default=28, show_default=True)
@click.option("--recent-daily-days", type=int, default=9, show_default=True)
@click.option("--include-extended-daily-baselines", is_flag=True, default=False)
@click.option("--sport", "sports", multiple=True)
@click.pass_context
def snapshot_cmd(
    ctx: click.Context,
    as_of: Any,
    baseline_days: int,
    recent_daily_days: int,
    include_extended_daily_baselines: bool,
    sports: tuple[str, ...],
) -> None:
    """Return a bounded recovery, load, execution, and plan snapshot."""
    reject_csv(ctx, "coach snapshot is nested and cannot be rendered as CSV; use --json.")
    sport_list = list(sports) or None
    try:
        budget = validate_snapshot_inputs(baseline_days, recent_daily_days, include_extended_daily_baselines, sport_list)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    ensure_authenticated(ctx.obj["config"])
    snapshot_date = as_of.date() if as_of is not None else today()
    result = collect_snapshot(
        snapshot_date,
        baseline_days,
        recent_daily_days,
        include_extended_daily_baselines,
        sport_list,
        budget,
    )
    if ctx.obj["config"].output_format == "json":
        render_output("json", "coach snapshot", [result], ())
        return
    echo_table(
        result["recovery"]["signals"],
        ("signal", "current_value", "baseline_median", "absolute_delta", "state"),
    )
    click.echo("")
    click.echo(
        "Note: the table shows recovery signals only. Use --json for load, plan, "
        "wellness, execution, and provenance."
    )
