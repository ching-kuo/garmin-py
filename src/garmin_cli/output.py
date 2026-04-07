"""Output formatting: JSON envelope, table, and CSV."""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date
from typing import Any, Optional

import click
from tabulate import tabulate


def make_envelope(
    command: str,
    data: list[dict[str, Any]],
    date_range: Optional[tuple[date, date]] = None,
) -> dict[str, Any]:
    """Wrap serialized data in the standard success JSON envelope.

    The returned envelope's ``data`` list is a shallow copy of the input
    to prevent the caller's original list from being mutated if the
    caller modifies the envelope's data field.
    """
    envelope: dict[str, Any] = {
        "ok": True,
        "command": command,
        "count": len(data),
        "data": list(data),
    }
    if date_range is not None:
        envelope["date_range"] = {
            "from": str(date_range[0]),
            "to": str(date_range[1]),
        }
    else:
        envelope["date_range"] = None
    return envelope


def make_error_envelope(
    command: str,
    error: str,
    error_code: str,
) -> dict[str, Any]:
    """Wrap an error in the standard error JSON envelope."""
    return {
        "ok": False,
        "command": command,
        "error": error,
        "error_code": error_code,
    }


def _default_serializer(obj: Any) -> str:
    """JSON serializer for non-standard types (e.g. date, datetime)."""
    if isinstance(obj, date):
        return obj.isoformat()
    return str(obj)


def echo_json(envelope: dict[str, Any]) -> None:
    """Print a JSON envelope to stdout (no ANSI codes)."""
    click.echo(json.dumps(envelope, indent=2, default=_default_serializer))


def echo_table(data: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    """Print data as a formatted table to stdout."""
    if not data:
        click.echo("(no data)")
        return

    rows = [
        [_format_cell(row.get(col)) for col in columns]
        for row in data
    ]
    click.echo(tabulate(rows, headers=list(columns), tablefmt="simple"))


def echo_csv(data: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    """Print data as CSV to stdout (no ANSI codes)."""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=list(columns),
        quoting=csv.QUOTE_MINIMAL,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in data:
        writer.writerow({col: _sanitize_csv_cell(row.get(col)) for col in columns})
    sys.stdout.write(buf.getvalue())


def render_output(
    output_format: str,
    command: str,
    data: list[dict[str, Any]],
    columns: tuple[str, ...],
    date_range: Optional[tuple[date, date]] = None,
) -> None:
    """Render data in the requested format (json, csv, or table)."""
    if output_format == "json":
        echo_json(make_envelope(command=command, data=data, date_range=date_range))
        return
    if output_format == "csv":
        echo_csv(data, columns)
        return
    echo_table(data, columns)


def _format_cell(value: Any) -> str:
    """Convert a cell value to a display string (for table output)."""
    if value is None:
        return ""
    return str(value)


_CSV_INJECT_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_cell(value: Any) -> str:
    """Convert a cell value to a CSV-safe string.

    Prefixes values that start with CSV formula-injection characters with a
    tab so spreadsheet software does not interpret them as formulas.
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in _CSV_INJECT_PREFIXES:
        return "\t" + text
    return text
