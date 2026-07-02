"""Unit tests for the front-end-agnostic performance service layer.

Exercises :func:`garmin_cli.services.performance.fetch_vo2max` directly with
injected endpoint/serializer fakes, independent of the CLI and MCP
front-ends (same style as tests/test_services/test_activities_service.py).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from garmin_cli.services.performance import fetch_vo2max


class _Recorder:
    """Records which endpoint fetch_vo2max routed to."""

    def __init__(self) -> None:
        self.vo2max_calls: list[date] = []
        self.latest_calls: int = 0

    def get_vo2max(self, target_date: date) -> list[dict[str, Any]]:
        # Two rows spanning two dates: proves the explicit-date branch returns
        # the serialized payload verbatim, without the latest-date reduction.
        self.vo2max_calls.append(target_date)
        return [
            {"calendarDate": "2026-03-09", "vo2MaxValue": 51.0, "sport": "generic"},
            {"calendarDate": str(target_date), "vo2MaxValue": 52.0, "sport": "generic"},
        ]

    def get_latest_vo2max(self) -> list[dict[str, Any]]:
        self.latest_calls += 1
        return [
            {"calendarDate": "2026-03-08", "vo2MaxValue": 52.0, "sport": "generic"},
            {"calendarDate": "2026-03-10", "vo2MaxValue": 54.0, "sport": "generic"},
            {"calendarDate": "2026-03-10", "vo2MaxValue": 55.0, "sport": "cycling"},
        ]


def _serialize_vo2max(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [
            {"date": item["calendarDate"], "vo2max": item["vo2MaxValue"], "sport": item.get("sport")}
            for item in raw
        ]
    return [{"date": raw["calendarDate"], "vo2max": raw["vo2MaxValue"], "sport": raw.get("sport")}]


def _select_latest_dated_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    latest = max(row["date"] for row in rows)
    return [row for row in rows if row["date"] == latest]


class TestFetchVo2max:

    def test_explicit_date_routes_to_get_vo2max(self) -> None:
        recorder = _Recorder()
        result = fetch_vo2max(
            date(2026, 3, 11),
            get_vo2max=recorder.get_vo2max,
            get_latest_vo2max=recorder.get_latest_vo2max,
            serialize_vo2max=_serialize_vo2max,
            select_latest_dated_rows=_select_latest_dated_rows,
        )
        assert recorder.vo2max_calls == [date(2026, 3, 11)]
        assert recorder.latest_calls == 0
        assert result == [
            {"date": "2026-03-09", "vo2max": 51.0, "sport": "generic"},
            {"date": "2026-03-11", "vo2max": 52.0, "sport": "generic"},
        ]

    def test_no_date_routes_to_get_latest_vo2max_and_selects_latest(self) -> None:
        recorder = _Recorder()
        result = fetch_vo2max(
            None,
            get_vo2max=recorder.get_vo2max,
            get_latest_vo2max=recorder.get_latest_vo2max,
            serialize_vo2max=_serialize_vo2max,
            select_latest_dated_rows=_select_latest_dated_rows,
        )
        assert recorder.vo2max_calls == []
        assert recorder.latest_calls == 1
        assert result == [
            {"date": "2026-03-10", "vo2max": 54.0, "sport": "generic"},
            {"date": "2026-03-10", "vo2max": 55.0, "sport": "cycling"},
        ]
