"""Performance service helpers shared by the CLI and MCP front-ends.

Owns the VO2 max "specific day vs latest" logic that was previously
copy-pasted between :mod:`garmin_cli.commands.performance` and the MCP
performance tool. Endpoint and serializer callables are injected rather than
imported directly so each front-end can pass its own module-level references
and keep per-front-end monkeypatching effective (same pattern as
:func:`garmin_cli.services.activities.fetch_laps_for_activity`).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

GetVo2maxFn = Callable[[date], Any]
GetLatestVo2maxFn = Callable[[], Any]
SerializeVo2maxFn = Callable[[Any], list[dict[str, Any]]]
SelectLatestFn = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


def fetch_vo2max(
    target_date: date | None,
    *,
    get_vo2max: GetVo2maxFn,
    get_latest_vo2max: GetLatestVo2maxFn,
    serialize_vo2max: SerializeVo2maxFn,
    select_latest_dated_rows: SelectLatestFn,
) -> list[dict[str, Any]]:
    """Resolve VO2 max rows for a specific day or the latest available.

    When ``target_date`` is given, the specific-day endpoint is queried and its
    serialized rows returned verbatim. When it is ``None``, the latest endpoint
    is queried and reduced to the single most-recent date's rows.
    """
    if target_date is not None:
        return serialize_vo2max(get_vo2max(target_date))
    return select_latest_dated_rows(serialize_vo2max(get_latest_vo2max()))
