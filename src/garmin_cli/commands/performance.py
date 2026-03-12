"""Performance commands."""
from __future__ import annotations

from datetime import date

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.endpoints.performance import (
    get_all_thresholds,
    get_latest_vo2max,
    get_lactate_threshold,
    get_vo2max,
)
from garmin_cli.output import render_output
from garmin_cli.serializers import (
    COLUMNS_THRESHOLDS,
    COLUMNS_VO2MAX,
    COLUMNS_ZONES,
    serialize_thresholds,
    serialize_vo2max,
    serialize_zones,
)


@click.group()
def performance() -> None:
    """Performance commands."""


def _latest_vo2max_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    dated_rows = [
        row for row in rows if isinstance(row.get("date"), str) and row.get("date")
    ]
    if not dated_rows:
        return rows[:1]
    latest_date = max(row["date"] for row in dated_rows)
    return [row for row in rows if row.get("date") == latest_date]


@performance.command("thresholds")
@click.pass_context
def thresholds_cmd(ctx: click.Context) -> None:
    """Get available threshold metrics."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_all_thresholds()
    data = serialize_thresholds(raw)
    render_output(ctx.obj["config"].output_format, "performance thresholds", data, COLUMNS_THRESHOLDS)


@performance.command("vo2max")
@click.option("--date", "value_date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.pass_context
def vo2max_cmd(ctx: click.Context, value_date: date | None) -> None:
    """Get VO2 max for a day."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_vo2max(value_date.date()) if value_date else get_latest_vo2max()
    data = serialize_vo2max(raw)
    if value_date is None:
        data = _latest_vo2max_rows(data)
    render_output(ctx.obj["config"].output_format, "performance vo2max", data, COLUMNS_VO2MAX)


@performance.command("zones")
@click.pass_context
def zones_cmd(ctx: click.Context) -> None:
    """Get lactate-threshold-derived zone inputs."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_lactate_threshold()
    data = serialize_zones(raw)
    render_output(ctx.obj["config"].output_format, "performance zones", data, COLUMNS_ZONES)
