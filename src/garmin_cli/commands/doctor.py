"""CLI doctor command."""
from __future__ import annotations

import click

from garmin_cli.doctor import run_checks
from garmin_cli.output import render_output

_COLUMNS = ("name", "ok", "detail", "error_code", "recovery_hint")


@click.command("doctor")
@click.option("--fast", is_flag=True, help="Skip the authenticated network probe.")
@click.option(
    "--format",
    "command_format",
    type=click.Choice(["table", "json"], case_sensitive=False),
    default=None,
    help="Output format for this command.",
)
@click.pass_context
def doctor(ctx: click.Context, fast: bool, command_format: str | None) -> None:
    """Diagnose configuration, authentication, and MCP readiness."""
    config = ctx.obj["config"]
    output_format = command_format or config.output_format
    if output_format not in {"table", "json"}:
        output_format = "table"
    results = run_checks(config, fast=fast)
    rows = [result.to_row() for result in results]
    render_output(output_format, "doctor", rows, _COLUMNS)
    if not all(result.ok for result in results):
        raise SystemExit(1)
