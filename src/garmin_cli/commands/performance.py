"""Performance commands."""
from __future__ import annotations

from datetime import datetime

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.commands._options import date_range_options, render_date_range
from garmin_cli.date_utils import CLICK_DATE_TYPE
from garmin_cli.endpoints.metrics import (
    FASTEST_SPLITS_SPORTS,
    FTP_HISTORY_SPORTS,
    MAX_FASTEST_SPLITS_BESTS,
    POWER_CURVE_SPORTS,
    get_acclimation_range,
    get_cycling_ability_range,
    get_endurance_score_range,
    get_fastest_splits,
    get_ftp_history,
    get_hill_score_range,
    get_power_curve,
    get_race_predictions,
)
from garmin_cli.endpoints.performance import (
    get_all_thresholds,
    get_latest_vo2max,
    get_lactate_threshold,
    get_personal_records,
    get_vo2max,
)
from garmin_cli.output import render_output
from garmin_cli.serializers import (
    COLUMNS_ENDURANCE_SCORE,
    COLUMNS_HILL_SCORE,
    COLUMNS_PERSONAL_RECORDS,
    COLUMNS_RACE_PREDICTIONS,
    COLUMNS_THRESHOLDS,
    COLUMNS_VO2MAX,
    COLUMNS_ZONES,
    select_latest_dated_rows,
    serialize_endurance_score,
    serialize_hill_score,
    serialize_personal_records,
    serialize_race_predictions,
    serialize_thresholds,
    serialize_vo2max,
    serialize_zones,
)
from garmin_cli.serializers.trends import (
    COLUMNS_ACCLIMATION,
    COLUMNS_CYCLING_ABILITY,
    COLUMNS_FASTEST_SPLITS,
    COLUMNS_FTP_HISTORY,
    COLUMNS_POWER_CURVE,
    serialize_acclimation,
    serialize_cycling_ability,
    serialize_fastest_splits,
    serialize_ftp_history,
    serialize_power_curve,
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


@performance.command("personal-records")
@click.pass_context
def personal_records_cmd(ctx: click.Context) -> None:
    """Get all-time personal records."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_personal_records()
    data = serialize_personal_records(raw)
    render_output(ctx.obj["config"].output_format, "performance personal-records", data, COLUMNS_PERSONAL_RECORDS)


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


@performance.command("ftp-history")
@click.option("--sport", type=click.Choice(FTP_HISTORY_SPORTS), default="cycling", show_default=True)
@date_range_options()
@click.pass_context
def ftp_history_cmd(
    ctx: click.Context,
    sport: str,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get daily functional threshold power (FTP) for a date range."""
    render_date_range(
        ctx,
        "performance ftp-history",
        lambda start, end: get_ftp_history(start, end, sport),
        serialize_ftp_history,
        COLUMNS_FTP_HISTORY,
        value_date,
        days,
        date_from,
        date_to,
    )


@performance.command("acclimation")
@date_range_options()
@click.pass_context
def acclimation_cmd(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get daily heat and altitude acclimation for a date range."""
    render_date_range(
        ctx,
        "performance acclimation",
        get_acclimation_range,
        serialize_acclimation,
        COLUMNS_ACCLIMATION,
        value_date,
        days,
        date_from,
        date_to,
    )


@performance.command("cycling-ability")
@date_range_options()
@click.pass_context
def cycling_ability_cmd(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get daily cycling ability scores for a date range."""
    render_date_range(
        ctx,
        "performance cycling-ability",
        get_cycling_ability_range,
        serialize_cycling_ability,
        COLUMNS_CYCLING_ABILITY,
        value_date,
        days,
        date_from,
        date_to,
    )


@performance.command("power-curve")
@click.option("--sport", type=click.Choice(POWER_CURVE_SPORTS), default="cycling", show_default=True)
@date_range_options()
@click.pass_context
def power_curve_cmd(
    ctx: click.Context,
    sport: str,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get best average power per duration across activities in a date range."""
    render_date_range(
        ctx,
        "performance power-curve",
        lambda start, end: get_power_curve(start, end, sport),
        serialize_power_curve,
        COLUMNS_POWER_CURVE,
        value_date,
        days,
        date_from,
        date_to,
    )


@performance.command("fastest-splits")
@click.option("--sport", type=click.Choice(FASTEST_SPLITS_SPORTS), default="running", show_default=True)
@click.option(
    "--bests",
    type=click.IntRange(1, MAX_FASTEST_SPLITS_BESTS),
    default=1,
    show_default=True,
    help="Fastest efforts to return per distance.",
)
@date_range_options()
@click.pass_context
def fastest_splits_cmd(
    ctx: click.Context,
    sport: str,
    bests: int,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get fastest times per standard distance across activities in a date range."""
    render_date_range(
        ctx,
        "performance fastest-splits",
        lambda start, end: get_fastest_splits(start, end, sport, bests),
        serialize_fastest_splits,
        COLUMNS_FASTEST_SPLITS,
        value_date,
        days,
        date_from,
        date_to,
    )
