"""Coaching-oriented read commands."""

from __future__ import annotations

from datetime import date
from typing import Any

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.output import echo_json, render_output
from garmin_cli.services.coaching_snapshot import collect_snapshot, validate_snapshot_inputs


@click.group("coach")
def coach() -> None:
    """AI-coaching data commands."""


@coach.command("snapshot")
@click.option("--date", "as_of", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
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
    sport_list = list(sports) or None
    try:
        budget = validate_snapshot_inputs(baseline_days, recent_daily_days, include_extended_daily_baselines, sport_list)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    snapshot_date = as_of.date() if as_of is not None else date.today()
    ensure_authenticated(ctx.obj["config"])
    result = collect_snapshot(
        snapshot_date,
        baseline_days,
        recent_daily_days,
        include_extended_daily_baselines,
        sport_list,
        budget,
    )
    if ctx.obj["config"].output_format == "json":
        echo_json(result)
        return
    render_output(
        ctx.obj["config"].output_format,
        "coach snapshot",
        result["recovery"]["signals"],
        ("signal", "current_value", "baseline_median", "absolute_delta", "state"),
    )
