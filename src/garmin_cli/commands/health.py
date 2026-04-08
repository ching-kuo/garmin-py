"""Health data commands."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.date_utils import CLICK_DATE_TYPE, resolve_click_dates
from garmin_cli.endpoints.health import (
    get_body_battery_range,
    get_hrv,
    get_resting_hr_range,
    get_sleep,
    get_spo2_range,
    get_stress_range,
    get_training_readiness_range,
    get_training_status,
    get_weight,
)
from garmin_cli.output import render_output
from garmin_cli.serializers import (
    COLUMNS_BODY_BATTERY,
    COLUMNS_HRV,
    COLUMNS_READINESS,
    COLUMNS_RESTING_HR,
    COLUMNS_SLEEP,
    COLUMNS_SPO2,
    COLUMNS_STATUS,
    COLUMNS_STRESS,
    COLUMNS_WEIGHT,
    serialize_body_battery,
    serialize_hrv,
    serialize_resting_hr,
    serialize_sleep,
    serialize_spo2,
    serialize_stress,
    serialize_training_readiness,
    serialize_training_status,
    serialize_weight,
)

_DATE_TYPE = CLICK_DATE_TYPE


def _render_health_range(
    ctx: click.Context,
    command_name: str,
    getter: Callable[[Any, Any], Any],
    serializer: Callable[[Any], list[dict[str, Any]]],
    columns: tuple[str, ...],
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
    *,
    ahead: int | None = None,
) -> None:
    start, end = resolve_click_dates(value_date, days, ahead, date_from, date_to)
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
def health() -> None:
    """Health data commands."""


@health.command()
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.option("--days", type=int)
@click.option("--ahead", type=int)
@click.option("--from", "date_from", type=_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=_DATE_TYPE, default=None)
@click.pass_context
def sleep(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    ahead: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get sleep data."""
    _render_health_range(
        ctx,
        "health sleep",
        get_sleep,
        serialize_sleep,
        COLUMNS_SLEEP,
        value_date,
        days,
        date_from,
        date_to,
        ahead=ahead,
    )


@health.command()
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.option("--days", type=int)
@click.option("--from", "date_from", type=_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=_DATE_TYPE, default=None)
@click.pass_context
def hrv(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get HRV data."""
    _render_health_range(
        ctx,
        "health hrv",
        get_hrv,
        serialize_hrv,
        COLUMNS_HRV,
        value_date,
        days,
        date_from,
        date_to,
    )


@health.command()
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.option("--days", type=int)
@click.option("--from", "date_from", type=_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=_DATE_TYPE, default=None)
@click.pass_context
def weight(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get weight data."""
    _render_health_range(
        ctx,
        "health weight",
        get_weight,
        serialize_weight,
        COLUMNS_WEIGHT,
        value_date,
        days,
        date_from,
        date_to,
    )


@health.command("body-battery")
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.option("--days", type=int)
@click.option("--from", "date_from", type=_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=_DATE_TYPE, default=None)
@click.pass_context
def body_battery(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get body battery data."""
    _render_health_range(
        ctx,
        "health body-battery",
        get_body_battery_range,
        serialize_body_battery,
        COLUMNS_BODY_BATTERY,
        value_date,
        days,
        date_from,
        date_to,
    )


@health.command()
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.option("--days", type=int)
@click.option("--from", "date_from", type=_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=_DATE_TYPE, default=None)
@click.pass_context
def stress(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get stress data."""
    _render_health_range(
        ctx,
        "health stress",
        get_stress_range,
        serialize_stress,
        COLUMNS_STRESS,
        value_date,
        days,
        date_from,
        date_to,
    )


@health.command()
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.option("--days", type=int)
@click.option("--from", "date_from", type=_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=_DATE_TYPE, default=None)
@click.pass_context
def spo2(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get pulse oximetry data."""
    _render_health_range(
        ctx,
        "health spo2",
        get_spo2_range,
        serialize_spo2,
        COLUMNS_SPO2,
        value_date,
        days,
        date_from,
        date_to,
    )


@health.command("resting-hr")
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.option("--days", type=int)
@click.option("--from", "date_from", type=_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=_DATE_TYPE, default=None)
@click.pass_context
def resting_hr(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get resting heart rate data."""
    _render_health_range(
        ctx,
        "health resting-hr",
        get_resting_hr_range,
        serialize_resting_hr,
        COLUMNS_RESTING_HR,
        value_date,
        days,
        date_from,
        date_to,
    )


@health.command("readiness")
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.option("--days", type=int)
@click.option("--from", "date_from", type=_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=_DATE_TYPE, default=None)
@click.pass_context
def readiness(
    ctx: click.Context,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """Get training readiness data."""
    _render_health_range(
        ctx,
        "health readiness",
        get_training_readiness_range,
        serialize_training_readiness,
        COLUMNS_READINESS,
        value_date,
        days,
        date_from,
        date_to,
    )


@health.command("status")
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.pass_context
def status(
    ctx: click.Context,
    value_date: datetime | None,
) -> None:
    """Get training status for a single day."""
    start, end = resolve_click_dates(value_date, None, None, None, None)
    ensure_authenticated(ctx.obj["config"])
    data = serialize_training_status(get_training_status(start))
    render_output(
        ctx.obj["config"].output_format,
        "health status",
        data,
        COLUMNS_STATUS,
        date_range=(start, end),
    )
