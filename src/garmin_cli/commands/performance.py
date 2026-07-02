"""Performance commands."""
from __future__ import annotations

from datetime import datetime

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.commands._options import date_range_options, render_date_range
from garmin_cli.date_utils import CLICK_DATE_TYPE
from garmin_cli.endpoints.metrics import (
    get_endurance_score_range,
    get_hill_score_range,
    get_race_predictions,
)
from garmin_cli.endpoints.performance import (
    get_all_thresholds,
    get_latest_vo2max,
    get_lactate_threshold,
    get_vo2max,
)
from garmin_cli.output import render_output
from garmin_cli.serializers import (
    COLUMNS_ENDURANCE_SCORE,
    COLUMNS_HILL_SCORE,
    COLUMNS_RACE_PREDICTIONS,
    COLUMNS_THRESHOLDS,
    COLUMNS_VO2MAX,
    COLUMNS_ZONES,
    select_latest_dated_rows,
    serialize_endurance_score,
    serialize_hill_score,
    serialize_race_predictions,
    serialize_thresholds,
    serialize_vo2max,
    serialize_zones,
)
from garmin_cli.services.performance import fetch_vo2max


@click.group()
def performance() -> None:
    """Performance commands."""


@performance.command("thresholds")
@click.pass_context
def thresholds_cmd(ctx: click.Context) -> None:
    """Get available threshold metrics."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_all_thresholds()
    data = serialize_thresholds(raw)
    render_output(ctx.obj["config"].output_format, "performance thresholds", data, COLUMNS_THRESHOLDS)


@performance.command("vo2max")
@click.option("--date", "value_date", type=CLICK_DATE_TYPE, default=None)
@click.pass_context
def vo2max_cmd(ctx: click.Context, value_date: datetime | None) -> None:
    """Get VO2 max for a day."""
    ensure_authenticated(ctx.obj["config"])
    data = fetch_vo2max(
        value_date.date() if value_date else None,
        get_vo2max=get_vo2max,
        get_latest_vo2max=get_latest_vo2max,
        serialize_vo2max=serialize_vo2max,
        select_latest_dated_rows=select_latest_dated_rows,
    )
    render_output(ctx.obj["config"].output_format, "performance vo2max", data, COLUMNS_VO2MAX)


@performance.command("zones")
@click.pass_context
def zones_cmd(ctx: click.Context) -> None:
    """Get lactate-threshold-derived zone inputs."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_lactate_threshold()
    data = serialize_zones(raw)
    render_output(ctx.obj["config"].output_format, "performance zones", data, COLUMNS_ZONES)


@performance.command("race-predictions")
@click.pass_context
def race_predictions_cmd(ctx: click.Context) -> None:
    """Get latest race predictions."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_race_predictions()
    data = serialize_race_predictions(raw)
    render_output(ctx.obj["config"].output_format, "performance race-predictions", data, COLUMNS_RACE_PREDICTIONS)


@performance.command("endurance-score")
@date_range_options()
@click.pass_context
def endurance_score_cmd(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get endurance score for a date range.

    Note: large date ranges may be slow — one API call is made per day.
    """
    render_date_range(
        ctx,
        "performance endurance-score",
        get_endurance_score_range,
        serialize_endurance_score,
        COLUMNS_ENDURANCE_SCORE,
        value_date,
        days,
        date_from,
        date_to,
    )


@performance.command("hill-score")
@date_range_options()
@click.pass_context
def hill_score_cmd(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get hill score for a date range.

    Note: large date ranges may be slow — one API call is made per day.
    """
    render_date_range(
        ctx,
        "performance hill-score",
        get_hill_score_range,
        serialize_hill_score,
        COLUMNS_HILL_SCORE,
        value_date,
        days,
        date_from,
        date_to,
    )
