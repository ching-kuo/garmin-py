"""File/stdin JSON and YAML input reading for workout commands."""
from __future__ import annotations

import json
from typing import Any

import click

from garmin_cli.exceptions import GarminCliError

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


def read_workout_input(
    file_path: str | None = None,
    use_stdin: bool = False,
    input_format: str | None = None,
) -> dict[str, Any]:
    """Read and parse workout JSON/YAML from file or stdin."""
    if use_stdin:
        stream = click.get_text_stream("stdin")
        raw_text = stream.read()
        fmt = input_format or "json"
    elif file_path is not None:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                raw_text = fh.read()
        except FileNotFoundError:
            raise GarminCliError(
                error=f"File not found: {file_path}",
                error_code="INVALID_INPUT",
            )
        if input_format is not None:
            fmt = input_format
        elif file_path.endswith(".yaml") or file_path.endswith(".yml"):
            fmt = "yaml"
        else:
            fmt = "json"
    else:
        raise GarminCliError(
            error="No input source provided. Use a file path or --stdin.",
            error_code="INVALID_INPUT",
        )

    if fmt == "yaml":
        if yaml is None:
            raise GarminCliError(
                error="YAML support requires pyyaml: pip install garmin-cli[yaml]",
                error_code="INVALID_INPUT",
            )
        try:
            result = yaml.safe_load(raw_text)
        except Exception as exc:
            raise GarminCliError(
                error=f"Failed to parse YAML input: {exc}",
                error_code="INVALID_INPUT",
            ) from exc
    else:
        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise GarminCliError(
                error=f"Failed to parse JSON input: {exc}",
                error_code="INVALID_INPUT",
            ) from exc

    if not isinstance(result, dict):
        raise GarminCliError(
            error="Input must be a JSON/YAML object (dict), not a list or scalar.",
            error_code="INVALID_INPUT",
        )

    return result
