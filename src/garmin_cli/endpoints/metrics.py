"""Metrics endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

from datetime import date
from typing import Any

import garth

from garmin_cli.endpoints._base import _collect_daily_range, _make_request


def _request(url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _make_request(garth.connectapi, url, params=params)


def get_race_predictions() -> list[Any]:
    result = _request("/metrics-service/metrics/racepredictions")
    if isinstance(result, dict):
        return [result]
    return result if result is not None else []


def get_endurance_score(day: date) -> dict[str, Any]:
    result = _request(
        "/metrics-service/metrics/endurancescore",
        params={"calendarDate": day.isoformat()},
    )
    return result if result is not None else {}


def get_endurance_score_range(start: date, end: date) -> list[Any]:
    return _collect_daily_range(get_endurance_score, start, end)


def get_hill_score(day: date) -> dict[str, Any]:
    result = _request(
        "/metrics-service/metrics/hillscore",
        params={"calendarDate": day.isoformat()},
    )
    return result if result is not None else {}


def get_hill_score_range(start: date, end: date) -> list[Any]:
    return _collect_daily_range(get_hill_score, start, end)
