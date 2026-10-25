"""File/stdin JSON and YAML input reading for workout commands."""
from __future__ import annotations

import json
import sys
from typing import Any

import yaml

from garmin_cli.exceptions import GarminCliError


def read_workout_input(
    file_path: str | None = None,
    use_stdin: bool = False,
    input_format: str | None = None,
) -> dict[str, Any]:
    """Read and parse workout JSON/YAML from file or stdin."""
    if use_stdin and file_path is not None:
        raise GarminCliError(
            error="Use either a file path or --stdin, not both.",
            error_code="INVALID_INPUT",
        )
    if use_stdin:
        source = "stdin"
        # None when fd 0 is closed (`<&-`); no .buffer if an embedder swapped in StringIO.
        stdin_bytes = getattr(sys.stdin, "buffer", None)
        if stdin_bytes is None:
            raise GarminCliError(error="stdin is not available.", error_code="INVALID_INPUT")
        raw_bytes = stdin_bytes.read()
        fmt = input_format or "json"
    elif file_path is not None:
        source = file_path
        try:
            with open(file_path, "rb") as fh:
                raw_bytes = fh.read()
        except FileNotFoundError as exc:
            raise GarminCliError(
                error=f"File not found: {file_path}",
                error_code="INVALID_INPUT",
            ) from exc
        except OSError as exc:
            raise GarminCliError(
                error=f"Cannot read {file_path}: {exc.strerror}",
                error_code="INVALID_INPUT",
            ) from exc
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

    # Always UTF-8, independent of the locale; utf-8-sig also strips the BOM
    # PowerShell and Notepad prepend.
    try:
        raw_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise GarminCliError(
            error=f"{source} is not valid UTF-8: {exc}",
            error_code="INVALID_INPUT",
        ) from exc

    if fmt == "yaml":
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
