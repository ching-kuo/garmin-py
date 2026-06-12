"""Performance commands."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.commands._options import date_range_options
from garmin_cli.date_utils import CLICK_DATE_TYPE, resolve_click_dates
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


def _render_performance_range(
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
    start, end = resolve_click_dates(value_date, days, None, date_from, date_to)
    ensure_authenticated(ctx.obj["config"])
    data = serializer(getter(start, end))
    render_output(
        ctx.obj["config"].output_format,
        command_name,
        data,
        columns,
        date_range=(start, end),
    )


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
    raw = get_vo2max(value_date.date()) if value_date else get_latest_vo2max()  # type: ignore[attr-defined]
    data = serialize_vo2max(raw)
    if value_date is None:
        data = select_latest_dated_rows(data)
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
    _render_performance_range(
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
    _render_performance_range(
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
