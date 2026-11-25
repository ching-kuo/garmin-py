"""Performance service helpers shared by the CLI and MCP front-ends.

Owns the VO2 max "specific day vs latest" logic that was previously
copy-pasted between :mod:`garmin_cli.commands.performance` and the MCP
performance tool.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from garmin_cli.endpoints.performance import get_latest_vo2max, get_vo2max
from garmin_cli.serializers import select_latest_dated_rows, serialize_vo2max


def fetch_vo2max(target_date: date | None) -> list[dict[str, Any]]:
    """Resolve VO2 max rows for a specific day or the latest available.

    When ``target_date`` is given, the specific-day endpoint is queried and its
    serialized rows returned verbatim. When it is ``None``, the latest endpoint
    is queried and reduced to the single most-recent date's rows.
    """
    if target_date is not None:
        return serialize_vo2max(get_vo2max(target_date))
    return select_latest_dated_rows(serialize_vo2max(get_latest_vo2max()))
