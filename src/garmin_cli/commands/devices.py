"""Device commands."""
from __future__ import annotations

import click

from garmin_cli.auth import ensure_authenticated
from garmin_cli.endpoints.devices import get_devices
from garmin_cli.output import render_output
from garmin_cli.serializers import (
    COLUMNS_DEVICE,
    serialize_device,
)


@click.group()
def device() -> None:
    """Device commands."""


@device.command("list")
@click.pass_context
def list_cmd(ctx: click.Context) -> None:
    """List registered Garmin devices."""
    ensure_authenticated(ctx.obj["config"])
    raw = get_devices()
    rows = serialize_device(raw)
    render_output(ctx.obj["config"].output_format, "device list", rows, COLUMNS_DEVICE)
