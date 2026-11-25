"""CLI doctor command."""
from __future__ import annotations

import click

from garmin_cli.commands._options import output_options
from garmin_cli.doctor import run_checks
from garmin_cli.output import render_output

_COLUMNS = ("name", "ok", "detail", "error_code", "recovery_hint")


@output_options
@click.command("doctor")
@click.option("--fast", is_flag=True, help="Skip the authenticated network probe.")
@click.pass_context
def doctor(ctx: click.Context, fast: bool) -> None:
    """Diagnose configuration, authentication, and MCP readiness."""
    config = ctx.obj["config"]
    results = run_checks(config, fast=fast)
    rows = [result.to_row() for result in results]
    render_output(config.output_format, "doctor", rows, _COLUMNS)
    if not all(result.ok for result in results):
        raise SystemExit(1)
