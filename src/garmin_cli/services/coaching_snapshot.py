"""Bounded Garmin fetch orchestration shared by CLI and MCP coaching surfaces."""

from __future__ import annotations

from datetime import date, timedelta
from functools import partial
from typing import Any, Callable

from garmin_cli.endpoints.activities import list_activities
from garmin_cli.endpoints.health import (
    get_body_battery_range,
    get_hrv,
    get_resting_hr,
    get_resting_hr_range,
    get_sleep,
    get_spo2,
    get_steps_range,
    get_stress,
    get_stress_range,
    get_training_readiness,
    get_training_status,
    get_weight,
)
from garmin_cli.endpoints.workouts import get_calendar_range
from garmin_cli.exceptions import GarminCliError
from garmin_cli.serializers import (
    serialize_activity_summary,
    serialize_body_battery,
    serialize_calendar_workout,
    serialize_hrv,
    serialize_resting_hr,
    serialize_sleep,
    serialize_spo2,
    serialize_steps,
    serialize_stress,
    serialize_training_readiness,
    serialize_training_status,
    serialize_weight,
)
from garmin_cli.services.coaching import build_coach_snapshot, coach_snapshot_request_budget

MAX_SNAPSHOT_REQUESTS = 30


def _snapshot_error(section: str, exc: GarminCliError) -> dict[str, Any]:
    category = {
        "RATE_LIMITED": "rate_limit",
        "NOT_FOUND": "not_found",
        "AUTH_MISSING": "authentication",
        "AUTH_FAILED": "authentication",
        "INVALID_INPUT": "validation",
    }.get(exc.error_code, "upstream")
    result: dict[str, Any] = {
        "section": section,
        "error_code": exc.error_code,
        "category": category,
        "message": "Garmin data for this section was unavailable.",
    }
    if exc.error_code == "RATE_LIMITED":
        result["recovery_hint"] = "Retry the snapshot later; do not retry immediately."
    return result


def validate_snapshot_inputs(
    baseline_days: int,
    recent_daily_days: int,
    include_extended_daily_baselines: bool,
    sports: list[str] | None,
) -> int:
    """Validate snapshot options and return their estimated request cost."""
    if baseline_days < 7 or baseline_days > 90:
        raise ValueError("baseline_days must be between 7 and 90")
    if recent_daily_days < 1 or recent_daily_days > 14:
        raise ValueError("recent_daily_days must be between 1 and 14")
    if sports is not None and (not all(isinstance(sport, str) and sport for sport in sports) or len(set(sports)) != len(sports)):
        raise ValueError("sports must be a list of unique non-empty strings")
    budget = coach_snapshot_request_budget(baseline_days, recent_daily_days, include_extended_daily_baselines)
    if budget > MAX_SNAPSHOT_REQUESTS:
        raise ValueError(
            f"snapshot request budget is {budget}, above the "
            f"{MAX_SNAPSHOT_REQUESTS}-request cap; reduce baseline_days or disable "
            "include_extended_daily_baselines"
        )
    return budget


def collect_snapshot(
    as_of: date,
    baseline_days: int,
    recent_daily_days: int,
    include_extended_daily_baselines: bool,
    sports: list[str] | None,
    estimated_requests: int,
) -> dict[str, Any]:
    """Fetch sequentially so a terminal 429 prevents new submissions."""
    baseline_start = as_of - timedelta(days=baseline_days)
    daily_days = baseline_days if include_extended_daily_baselines else recent_daily_days
    recent_start = as_of - timedelta(days=daily_days)
    sections: dict[str, list[dict[str, Any]]] = {}
    unavailable: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = []
    complete = True
    aborted = False
    completed_requests = 0

    def fetch(
        section: str,
        call: Callable[[], Any],
        serialize: Callable[[Any], list[dict[str, Any]]],
        cost: int = 1,
    ) -> bool:
        # ``completed_requests`` counts fully completed sections; a fan-out
        # aborted mid-range charges nothing, so it is a lower bound.
        nonlocal complete, aborted, completed_requests
        if aborted:
            return False
        try:
            raw = call()
            completed_requests += cost
            rows = serialize(raw)
            sections[section] = rows
            if not rows:
                unavailable.append({"section": section, "reason": "no_data"})
            return True
        except GarminCliError as exc:
            if exc.error_code in {"AUTH_MISSING", "AUTH_FAILED", "MFA_REQUIRED", "INVALID_INPUT"}:
                raise
            complete = False
            sections[section] = []
            if exc.error_code == "NOT_FOUND":
                unavailable.append({"section": section, "reason": "not_found"})
                return True
            errors.append(_snapshot_error(section, exc))
            if exc.error_code == "RATE_LIMITED":
                aborted = True
                return False
            return True

    fetch("sleep", lambda: get_sleep(baseline_start, as_of), serialize_sleep)
    fetch("hrv", lambda: get_hrv(baseline_start, as_of), serialize_hrv)
    fetch("body_battery", lambda: get_body_battery_range(baseline_start, as_of), serialize_body_battery)
    # Garmin's daily-steps endpoint rejects spans wider than 28 dates (live
    # 400: "difference ... cannot be more than 28 days"), so cap this window;
    # steps feed the wellness section only, never the baselines.
    steps_start = max(baseline_start, as_of - timedelta(days=27))
    fetch("steps", lambda: get_steps_range(steps_start, as_of), serialize_steps)
    fetch("weight", lambda: get_weight(baseline_start, as_of), serialize_weight)
    fetch(
        "activities",
        lambda: list_activities(100, 0, None, None, baseline_start, as_of),
        serialize_activity_summary,
    )
    # The daily-range fan-out throttles submissions (GARMIN_CLI_DAILY_CALL_DELAY)
    # and cancels pending days on the first failure, so a terminal 429 inside a
    # section still honors the stop/cancel/drain contract at section level.
    for section, range_getter, getter, serializer in (
        ("resting_hr", get_resting_hr_range, get_resting_hr, serialize_resting_hr),
        ("stress", get_stress_range, get_stress, serialize_stress),
    ):
        fetch(
            section,
            partial(range_getter, recent_start, as_of - timedelta(days=1)),
            serializer,
            cost=daily_days,
        )
        fetch(f"current_{section}", partial(getter, as_of), serializer)
    fetch("training_readiness", lambda: get_training_readiness(as_of), serialize_training_readiness)
    fetch("spo2", lambda: get_spo2(as_of), serialize_spo2)
    fetch("training_status", lambda: get_training_status(as_of), serialize_training_status)
    # Seven dates (today plus six): the weekly calendar walk steps 7 days from
    # its start, so this window costs exactly one request; an 8th date would
    # trigger a second week and blow the documented budget.
    fetch(
        "calendar",
        lambda: get_calendar_range(as_of, as_of + timedelta(days=6)),
        lambda raw: serialize_calendar_workout({"calendarItems": raw}),
    )
    return build_coach_snapshot(
        as_of=as_of,
        baseline_days=baseline_days,
        daily_baseline_days=daily_days,
        sections=sections,
        unavailable=unavailable,
        errors=errors,
        complete=complete,
        aborted=aborted,
        estimated_requests=estimated_requests,
        completed_requests=completed_requests,
        sports=sports,
    )
