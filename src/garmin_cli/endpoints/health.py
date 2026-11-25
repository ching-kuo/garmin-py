"""Health endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from garmin_cli import backend as garth
from garmin_cli.endpoints._base import (
    _collect_daily_range,
    _dates,
    _make_request,
    _make_typed_request,
)
from garmin_cli.exceptions import GarminCliError


def _request(url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _make_request(garth.connectapi, url, params=params)


def get_sleep(start: date, end: date) -> Any:
    return _request(
        "/wellness-service/wellness/dailySleeps",
        params={"startDate": start.isoformat(), "endDate": end.isoformat()},
    )


def get_hrv(start: date, end: date) -> Any:
    if start == end:
        return _request(f"/hrv-service/hrv/{start.isoformat()}")
    return _request(
        f"/hrv-service/hrv/daily/{start.isoformat()}/{end.isoformat()}"
    )


def get_weight(start: date, end: date) -> Any:
    return _request(
        "/weight-service/weight/dateRange",
        params={"startDate": start.isoformat(), "endDate": end.isoformat()},
    )


def get_daily_summary_range(start: date, end: date) -> list[Any]:
    """Fetch daily summaries for a range in one call (v2 ``dailysummaries``).

    Replaces a per-day fan-out over ``usersummary/daily``; verified live on
    2026-11-09 to return all 90 days of a 90-day span in a single response.
    Items use the nested v2 shape (``movement``/``calories``/...).
    """
    result = _request(
        "/usersummary-service/v2/dailysummaries",
        params={"startDate": start.isoformat(), "endDate": end.isoformat()},
    )
    data = result.get("data") if isinstance(result, dict) else None
    return data if isinstance(data, list) else []


# Inclusive dates per request (verified live 2026-11): steps, stress and
# heartRate stats 400 above 28 dates; intensity minutes ("im") above 31.
_STATS_MAX_DATES: dict[str, int] = {"im": 31}
_DEFAULT_STATS_MAX_DATES = 28


def _get_stats_range(stat: str, start: date, end: date) -> list[Any]:
    """Fetch a usersummary stats range in date-ordered windows within Garmin's span limit."""
    window = timedelta(days=_STATS_MAX_DATES.get(stat, _DEFAULT_STATS_MAX_DATES) - 1)
    rows: list[Any] = []
    chunk_start = start
    while chunk_start <= end:
        # Compare before adding so dates near date.max never overflow.
        chunk_end = chunk_start + window if end - chunk_start > window else end
        result = _request(
            f"/usersummary-service/stats/{stat}/daily/{chunk_start.isoformat()}/{chunk_end.isoformat()}"
        )
        if isinstance(result, dict):
            rows.append(result)
        elif result is not None:
            rows.extend(result)
        if chunk_end == end:
            break
        chunk_start = chunk_end + timedelta(days=1)
    return rows


def get_steps_range(start: date, end: date) -> list[Any]:
    return _get_stats_range("steps", start, end)


def get_intensity_minutes_range(start: date, end: date) -> list[Any]:
    return _get_stats_range("im", start, end)


def get_body_battery_range(start: date, end: date) -> list[Any]:
    """Fetch body battery for a date range in a single ranged call.

    Garmin removed the per-day ``/wellness/bodyBattery/{date}`` endpoint
    (404 as of 2026-07); ``reports/daily`` is the path garminconnect 0.3.5
    itself uses and returns one item per day.
    """
    result = _request(
        "/wellness-service/wellness/bodyBattery/reports/daily",
        params={"startDate": start.isoformat(), "endDate": end.isoformat()},
    )
    if isinstance(result, dict):
        return [result]
    return result if result is not None else []


def get_stress(day: date) -> Any:
    return _request(f"/wellness-service/wellness/dailyStress/{day.isoformat()}")


def get_stress_range(start: date, end: date) -> list[Any]:
    # Stays per day: the stats-service stress range has only the average
    # (overallStressLevel) and durations, not the max_stress column.
    return _collect_daily_range(get_stress, start, end)


def get_spo2(day: date) -> Any:
    return _request(f"/wellness-service/wellness/daily/spo2/{day.isoformat()}")


def get_spo2_range(start: date, end: date) -> list[Any]:
    return _collect_daily_range(get_spo2, start, end)


def get_resting_hr_range(start: date, end: date) -> list[dict[str, Any]]:
    """Resting HR for ``[start, end]``, one row per date ascending.

    One range request (366 dates work live, above every caller's span cap),
    plus one per-day dailyHeartRate request when the series has no value for
    ``end``: it was not confirmed live that the series carries today's value
    during the day. Upstream drops days without a value and returns floats;
    days are refilled and whole values made ints so rows match the former
    per-day dailyHeartRate rows.
    """
    if start > end:
        return []
    rows = _make_typed_request(garth.get_rhr_daily, start.isoformat(), end.isoformat())
    by_date = {row.get("calendarDate"): row.get("value") for row in rows or [] if isinstance(row, dict)}
    if by_date.get(end.isoformat()) is None:
        try:
            day_row = _make_typed_request(garth.get_heart_rates, end.isoformat())
        except GarminCliError as exc:
            if exc.error_code != "NOT_FOUND":
                raise
            day_row = None
        if isinstance(day_row, dict):
            by_date[end.isoformat()] = day_row.get("restingHeartRate")
    result: list[dict[str, Any]] = []
    for day in _dates(start, end):
        value = by_date.get(day.isoformat())
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        result.append({"calendarDate": day.isoformat(), "restingHeartRate": value})
    return result


def get_training_readiness_range(start: date, end: date) -> list[dict[str, Any]]:
    """One training-readiness entry per day in one request, date ascending.

    The range takes 366 dates live and returns every recalculation of a day
    (newest first, tagged by ``inputContext``). The day's row is its latest
    morning ``AFTER_WAKEUP_RESET`` entry, Garmin's daily score, or without one
    its latest entry; ``latest_score`` / ``latest_level`` carry the day's
    latest entry. "Latest" is by UTC ``timestamp`` when every entry of the day
    has one (local time repeats an hour at DST fall-back), else Garmin's order.
    """
    if start > end:
        return []
    result = _request(
        f"/metrics-service/metrics/trainingreadiness/{start.isoformat()}/{end.isoformat()}"
    )
    entries = [result] if isinstance(result, dict) else result if isinstance(result, list) else []
    by_day: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        calendar_date, local = entry.get("calendarDate"), entry.get("timestampLocal")
        if not isinstance(calendar_date, str | None) or not isinstance(local, str | None):
            continue
        day = calendar_date or (local[:10] if local else None)
        if day and start.isoformat() <= day <= end.isoformat():
            by_day.setdefault(day, []).append(entry)
    rows: list[dict[str, Any]] = []
    for day in sorted(by_day):
        oldest_first = by_day[day][::-1]
        if all(isinstance(entry.get("timestamp"), str) for entry in oldest_first):
            oldest_first.sort(key=lambda entry: entry["timestamp"])  # stable: Garmin's order breaks ties
        latest = oldest_first[-1]
        mornings = [entry for entry in oldest_first if entry.get("inputContext") == "AFTER_WAKEUP_RESET"]
        rows.append({
            **(mornings[-1] if mornings else latest),
            "calendarDate": day,
            "latest_score": latest.get("score"),
            "latest_level": latest.get("level"),
        })
    return rows


def get_training_status(day: date) -> Any:
    # The old /training-info-service/.../training-status/{date} path 404s
    # (verified live 2026-07-07); the aggregated metrics-service path is what
    # garminconnect 0.3.5 itself uses and carries status + acute/chronic load
    # + load balance + ACWR in one payload.
    return _request(
        f"/metrics-service/metrics/trainingstatus/aggregated/{day.isoformat()}"
    )
