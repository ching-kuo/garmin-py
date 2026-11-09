"""Metrics endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, get_args

from garmin_cli import backend as garth
from garmin_cli.endpoints._base import (
    _collect_daily_range,
    _make_request,
    _make_typed_request,
)


def _request(url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _make_request(garth.connectapi, url, params=params)


def get_race_predictions() -> Any:
    # Upstream returns one flat dict keyed by race distance (time5K,
    # time10K, ...) rather than a list of per-race objects; the reshape into
    # rows happens in serialize_race_predictions.
    result = _make_typed_request(garth.get_race_predictions)
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


# --- Performance trends (paths/params verified live 2026-11-09) -------------

# Sports each trend endpoint accepts. The power curve rejects running with a
# 400 ("Supported types are: cycling and rowing").
FtpHistorySport = Literal["cycling", "running"]
PowerCurveSport = Literal["cycling", "rowing"]
FastestSplitsSport = Literal["running", "cycling"]
FTP_HISTORY_SPORTS: tuple[str, ...] = get_args(FtpHistorySport)
POWER_CURVE_SPORTS: tuple[str, ...] = get_args(PowerCurveSport)
FASTEST_SPLITS_SPORTS: tuple[str, ...] = get_args(FastestSplitsSport)
MAX_FASTEST_SPLITS_BESTS = 10


def get_ftp_history(start: date, end: date, sport: str) -> list[Any]:
    """Daily functional threshold power (FTP) values in [start, end]."""
    result = _request(
        f"/biometric-service/stats/functionalThresholdPower/range/{start.isoformat()}/{end.isoformat()}",
        params={"sport": sport.upper(), "aggregation": "daily", "aggregationStrategy": "LATEST"},
    )
    return result if isinstance(result, list) else []


def get_acclimation_range(start: date, end: date) -> list[Any]:
    """Daily heat and altitude acclimation in [start, end]."""
    result = _request(
        f"/metrics-service/metrics/heataltitudeacclimation/daily/{start.isoformat()}/{end.isoformat()}"
    )
    return result if isinstance(result, list) else []


def get_cycling_ability_range(start: date, end: date) -> dict[str, Any]:
    """Cycling ability scores keyed by date (``cyclingAbilitiesMap``)."""
    result = _request(
        "/metrics-service/metrics/cycling-ability",
        params={"startDate": start.isoformat(), "endDate": end.isoformat(), "aggregation": "DAILY"},
    )
    return result if isinstance(result, dict) else {}


def get_power_curve(start: date, end: date, sport: str) -> dict[str, Any]:
    """Best average power per duration over activities in [start, end]."""
    result = _request(
        "/fitnessstats-service/powerCurve",
        params={"startDate": start.isoformat(), "endDate": end.isoformat(), "sport": sport},
    )
    return result if isinstance(result, dict) else {}


def get_fastest_splits(start: date, end: date, sport: str, bests: int) -> list[Any]:
    """Fastest times per standard distance, ``bests`` per distance."""
    result = _request(
        "/activitylist-service/activities/fastest-splits",
        params={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "activityType": sport,
            "numberOfBests": bests,
        },
    )
    return result if isinstance(result, list) else []
