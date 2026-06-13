"""Activity commands."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.commands._options import validate_limit
from garmin_cli.exceptions import GarminCliError
from garmin_cli.date_utils import CLICK_DATE_TYPE, resolve_click_dates
from garmin_cli.endpoints.activities import (
    activity_type_key,
    delete_activity,
    download_activity,
    extension_for_format,
    get_activity,
    get_activity_details,
    get_activity_hr_in_timezones,
    get_activity_splits,
    get_activity_typed_splits,
    get_activity_weather,
    get_multisport_children,
    is_multisport_parent,
    list_activities,
    upload_activity,
)
from garmin_cli.metrics.sport_profile import SportProfile
from garmin_cli.output import (
    echo_csv,
    echo_json,
    echo_table,
    make_envelope,
    render_capability_footnote,
    render_output,
)
from garmin_cli.serializers import (
    COLUMNS_ACTIVITY_DELETE,
    COLUMNS_ACTIVITY_DETAIL,
    COLUMNS_ACTIVITY_DOWNLOAD,
    COLUMNS_ACTIVITY_HR_ZONES,
    COLUMNS_ACTIVITY_SUMMARY,
    COLUMNS_ACTIVITY_UPLOAD,
    COLUMNS_ACTIVITY_WEATHER,
    COLUMNS_METRICS_DESCRIPTORS,
    COLUMNS_MULTISPORT_CHILDREN,
    columns_for_lap,
    columns_for_sport,
    manifest_summary_counts,
    serialize_activity_delete,
    serialize_activity_detail,
    serialize_activity_download,
    serialize_activity_hr_zones,
    serialize_activity_laps,
    serialize_activity_summary,
    serialize_activity_upload,
    serialize_capability_manifest,
    serialize_metrics_descriptors,
    serialize_multisport_children,
)
from garmin_cli.services.activities import (
    build_capability_manifest,
    fetch_laps_for_activity,
)


_DATE_TYPE = CLICK_DATE_TYPE


@click.group()
def activity() -> None:
    """Activity commands."""


@activity.command("list")
@click.option("--limit", type=int, default=20)
@click.option("--type", "activity_type", type=str, default=None)
@click.option("--search", type=str, default=None)
@click.option("--date", "value_date", type=_DATE_TYPE, default=None)
@click.option("--days", type=int, default=None)
@click.option("--from", "date_from", type=_DATE_TYPE, default=None)
@click.option("--to", "date_to", type=_DATE_TYPE, default=None)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    limit: int,
    activity_type: str | None,
    search: str | None,
    value_date: datetime | None,
    days: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    """List recent activities, optionally filtered by date range."""
    validate_limit(limit)
    has_date_args = any(x is not None for x in (value_date, days, date_from, date_to))
    start_date = None
    end_date = None
    if has_date_args:
        start_date, end_date = resolve_click_dates(value_date, days, None, date_from, date_to)
    ensure_authenticated(ctx.obj["config"])
    raw = list_activities(
        limit=limit, start=0, activity_type=activity_type, search=search,
        start_date=start_date, end_date=end_date,
    )
    data = serialize_activity_summary(raw)
    date_range = (start_date, end_date) if start_date is not None else None
    render_output(
        ctx.obj["config"].output_format, "activity list", data, COLUMNS_ACTIVITY_SUMMARY,
        date_range=date_range,  # type: ignore[arg-type]
    )


def _fetch_laps_for_activity(raw: dict, activity_id: str) -> tuple[list[dict], SportProfile]:
    """Fetch laps for an activity, handling multisport parents.

    For multisport parents, iterates child legs, fetches each child's laps,
    and stamps ``leg_index`` (0-based) onto every returned row. The returned
    profile is the parent's profile (for table column hint); per-row
    sport-specificity remains intact via the columns each row carries.

    Thin wrapper over :func:`garmin_cli.services.activities.fetch_laps_for_activity`
    that binds this module's endpoint/serializer references so test patches on
    ``garmin_cli.commands.activities.*`` stay effective.
    """
    return fetch_laps_for_activity(
        raw,
        activity_id,
        activity_type_key=activity_type_key,
        is_multisport_parent=is_multisport_parent,
        get_multisport_children=get_multisport_children,
        splits_fn=get_activity_splits,
        typed_splits_fn=get_activity_typed_splits,
        serialize_laps=serialize_activity_laps,
    )


@activity.command("get")
@click.argument("activity_id")
@click.option("--detail", "-d", is_flag=True, default=False)
@click.option("--laps", "include_laps", is_flag=True, default=False,
              help="Include lap-by-lap data (auto-routes pool swim to per-pool-length).")
@click.pass_context
def get_cmd(ctx: click.Context, activity_id: str, detail: bool, include_laps: bool) -> None:
    """Get a single activity by ID. For multisport activities, shows each child sport."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_activity(activity_id)
    fmt = ctx.obj["config"].output_format
    data = serialize_activity_detail(raw) if detail else serialize_activity_summary(raw)

    if detail:
        # CSV uses the stable union schema; tables use sport-aware ordering so
        # only sport-applicable columns appear (no clutter of empty cells).
        type_key = activity_type_key(raw)
        csv_columns = COLUMNS_ACTIVITY_DETAIL
        table_columns = columns_for_sport(type_key)
    else:
        csv_columns = COLUMNS_ACTIVITY_SUMMARY
        table_columns = COLUMNS_ACTIVITY_SUMMARY

    children_raw: list[dict] = []
    child_data: list[dict] = []
    if is_multisport_parent(raw):
        fetched = get_multisport_children(raw)
        if fetched:
            children_raw = fetched
            child_data = serialize_multisport_children(fetched)

    laps_rows: list[dict] = []
    laps_profile = None
    if include_laps:
        laps_rows, laps_profile = _fetch_laps_for_activity(raw, activity_id)

    # Capability manifest: only when --detail is set. Multisport parent
    # envelopes union per-child manifests with leg_index attached.
    manifest: list[dict] = []
    if detail:
        manifest = build_capability_manifest(
            raw,
            data,
            children_raw,
            serialize_detail=serialize_activity_detail,
            serialize_manifest=serialize_capability_manifest,
        )

    if fmt == "json":
        envelope = make_envelope(command="activity get", data=data)
        if child_data:
            envelope["children"] = child_data
        if include_laps:
            envelope["laps"] = laps_rows
        if manifest:
            envelope["unavailable"] = manifest
        echo_json(envelope)
    elif fmt == "table":
        echo_table(data, table_columns)
        if child_data:
            click.echo("")
            click.echo("Child activities:")
            echo_table(child_data, COLUMNS_MULTISPORT_CHILDREN)
        if include_laps:
            click.echo("")
            click.echo("Laps:")
            echo_table(laps_rows, columns_for_lap(laps_profile))  # type: ignore[arg-type]
        if manifest:
            footnote = render_capability_footnote(*manifest_summary_counts(manifest))
            if footnote:
                click.echo("")
                click.echo(footnote)
    else:
        # CSV: parent rows + (optionally) children rows + (optionally) laps rows
        # Manifest is intentionally omitted from CSV output (back-compat).
        if child_data:
            if detail:
                echo_csv(data, csv_columns)
                click.echo("")
            echo_csv(child_data, COLUMNS_MULTISPORT_CHILDREN)
        else:
            echo_csv(data, csv_columns)
        if include_laps:
            click.echo("")
            lap_columns = columns_for_lap(laps_profile)  # type: ignore[arg-type]
            echo_csv(laps_rows, lap_columns)


@activity.command("laps")
@click.argument("activity_id")
@click.pass_context
def laps_cmd(ctx: click.Context, activity_id: str) -> None:
    """Get lap-by-lap data for an activity (per-pool-length for pool swim)."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_activity(activity_id)
    rows, profile = _fetch_laps_for_activity(raw, activity_id)
    columns = columns_for_lap(profile)
    render_output(ctx.obj["config"].output_format, "activity laps", rows, columns)


@activity.command("zones")
@click.argument("activity_id")
@click.pass_context
def zones_cmd(ctx: click.Context, activity_id: str) -> None:
    """Get HR time-in-zone breakdown for an activity."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_activity_hr_in_timezones(activity_id)
    rows = serialize_activity_hr_zones(raw)
    render_output(ctx.obj["config"].output_format, "activity zones", rows, COLUMNS_ACTIVITY_HR_ZONES)


@activity.command("weather")
@click.argument("activity_id")
@click.pass_context
def weather_cmd(ctx: click.Context, activity_id: str) -> None:
    """Get weather data for an activity."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_activity_weather(activity_id)
    data = [raw] if isinstance(raw, dict) else (raw or [])
    render_output(ctx.obj["config"].output_format, "activity weather", data, COLUMNS_ACTIVITY_WEATHER)


@activity.command("metrics-describe")
@click.argument("activity_id")
@click.pass_context
def metrics_describe_cmd(ctx: click.Context, activity_id: str) -> None:
    """Describe the dynamic metric schema for an activity's detail stream.

    Returns one row per metric descriptor: key, unit, metricsIndex.
    Use this to discover what metrics a watch recorded for a specific activity.
    """
    ensure_authenticated(ctx.obj["config"])
    raw = get_activity_details(activity_id)
    rows = serialize_metrics_descriptors(raw)
    render_output(ctx.obj["config"].output_format, "activity metrics-describe", rows, COLUMNS_METRICS_DESCRIPTORS)


@activity.command("download")
@click.argument("activity_id")
@click.option(
    "--fmt",
    type=click.Choice(["original", "tcx", "gpx", "kml", "csv"]),
    default="original",
    help="Download format. 'original' is the FIT file in a ZIP archive.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Output file path. Defaults to activity_<id><ext> in the current directory.",
)
@click.option("--force", is_flag=True, default=False, help="Overwrite the output file if it exists.")
@click.pass_context
def download_cmd(
    ctx: click.Context,
    activity_id: str,
    fmt: str,
    output_path: str | None,
    force: bool,
) -> None:
    """Download an activity's file (original FIT/ZIP, TCX, GPX, KML, or CSV) to disk."""
    ensure_authenticated(ctx.obj["config"])
    target = Path(output_path) if output_path else Path.cwd() / f"activity_{activity_id}{extension_for_format(fmt)}"
    if target.exists() and not force:
        raise GarminCliError(
            error=f"Output file already exists: {target}. Use --force to overwrite.",
            error_code="INVALID_INPUT",
        )
    if not target.parent.is_dir():
        raise GarminCliError(
            error=f"Output directory does not exist: {target.parent}",
            error_code="INVALID_INPUT",
        )
    payload = download_activity(activity_id, fmt)
    target.write_bytes(payload)
    rows = serialize_activity_download(activity_id, fmt, str(target), len(payload))
    render_output(ctx.obj["config"].output_format, "activity download", rows, COLUMNS_ACTIVITY_DOWNLOAD)


@activity.command("upload")
@click.argument("file_path", metavar="FILE", type=click.Path(dir_okay=False))
@click.pass_context
def upload_cmd(ctx: click.Context, file_path: str) -> None:
    """Upload an activity file (FIT, GPX, or TCX) to Garmin Connect."""
    ensure_authenticated(ctx.obj["config"])
    raw = upload_activity(file_path)
    rows = serialize_activity_upload(file_path, raw)
    render_output(ctx.obj["config"].output_format, "activity upload", rows, COLUMNS_ACTIVITY_UPLOAD)


@activity.command("delete")
@click.argument("activity_id")
@click.option("--confirm", is_flag=True, default=False)
@click.pass_context
def delete_cmd(ctx: click.Context, activity_id: str, confirm: bool) -> None:
    """Delete an activity by ID."""
    ensure_authenticated(ctx.obj["config"])
    if not confirm:
        click.confirm(f"Delete activity {activity_id}?", abort=True)
    delete_activity(activity_id)
    rows = serialize_activity_delete(activity_id)
    render_output(ctx.obj["config"].output_format, "activity delete", rows, COLUMNS_ACTIVITY_DELETE)
