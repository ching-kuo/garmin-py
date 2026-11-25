"""Reliable lap-to-workout interval mapping for target reconciliation."""
from __future__ import annotations

import math
from typing import Any

_TARGET_NAMES = {
    "heart.rate.zone": "hr",
    "speed.zone": "pace",
    "power.zone": "power",
    "cadence.zone": "cadence",
}


def _number(value: Any) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return float(value)
    return None


def _expanded_steps(steps: Any) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict):
            continue
        if step.get("type") != "repeat":
            expanded.append(step)
            continue
        count = step.get("count")
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            children = _expanded_steps(step.get("steps"))
            for _ in range(count):
                expanded.extend(children)
    return expanded


def _lap_cadence(lap: dict[str, Any]) -> float | None:
    return _number(lap.get("avg_cadence_spm")) or _number(lap.get("avg_cadence_rpm"))


def _lap_value(lap: dict[str, Any], target_type: str) -> float | None:
    if target_type == "pace":
        distance = _number(lap.get("distance_km"))
        duration = _number(lap.get("duration_min"))
        if distance is not None and duration is not None and duration > 0:
            return distance * 1000.0 / (duration * 60.0)
        return None
    if target_type == "power":
        return _number(lap.get("avg_power_w"))
    if target_type == "cadence":
        return _lap_cadence(lap)
    return _number(lap.get("avg_hr"))


_TOP_HR_ZONE = 5


def power_zone_bounds(zone: Any, power_zones: list[dict[str, Any]]) -> dict[str, float | None] | None:
    """Watt band of *zone* from serialized power zone rows; max None is open-ended."""
    row = next(
        (row for row in power_zones if row.get("kind") == "power" and row.get("zone") == zone),
        None,
    )
    low = _number(row.get("low")) if row else None
    return None if row is None or low is None else {"min": low, "max": _number(row.get("high"))}


def _in_band(value: float, low: float, high: float, high_inclusive: bool) -> bool:
    return low <= value and (value <= high if high_inclusive else value < high)


def _boundary_reason(target_type: str) -> str:
    """Reason for a prescription without numeric bounds."""
    return "missing_power_zone_boundaries" if target_type == "power" else f"missing_{target_type}_target_boundaries"


def _band(
    target: dict[str, Any],
    target_type: str,
    rows: dict[Any, dict[str, Any]],
    power_zones: list[dict[str, Any]],
) -> tuple[dict[str, Any], float | None, float | None, bool]:
    """Return (prescribed band, low, high, whether high is inclusive).

    *rows* maps HR zone number to its time-in-zone row; *power_zones* are the
    athlete's serialized power zone rows for the activity's sport.
    """
    if "zone" not in target:
        prescribed = {"min": target.get("min"), "max": target.get("max")}
        return prescribed, _number(target.get("min")), _number(target.get("max")), True
    prescribed = {"zone": target.get("zone")}
    if target_type == "power":
        bounds = power_zone_bounds(target.get("zone"), power_zones)
        if bounds is None:
            return prescribed, None, None, True
        # A zone ends below the next zone's floor (exclusive).
        return prescribed, bounds["min"], math.inf if bounds["max"] is None else bounds["max"], False
    if target_type != "hr":
        return prescribed, None, None, True
    zone = target.get("zone")
    row = rows.get(zone, {})
    low = _number(row.get("zone_low_bpm"))
    high = _number(row.get("zone_high_bpm"))
    if high is not None or low is None:
        return prescribed, low, high, True
    # Live time-in-zone rows carry floors only: a zone ends just below the next
    # zone's floor (exclusive), and only the top zone is open-ended.
    if zone == _TOP_HR_ZONE:
        return prescribed, low, math.inf, True
    next_floor = _number(rows.get(zone + 1, {}).get("zone_low_bpm")) if isinstance(zone, int) else None
    return prescribed, low, next_floor, False


def compare_interval_completion(
    workout: dict[str, Any],
    laps: list[dict[str, Any]],
    hr_zones: list[dict[str, Any]],
    power_zones: list[dict[str, Any]] | None = None,
    power_zone_reason: str | None = None,
) -> dict[str, Any]:
    """Map laps only when the expanded workout and lap counts match exactly.

    *power_zone_reason* explains an unresolvable power zone number (for
    example a sport mismatch) instead of the generic missing-boundaries reason.
    """
    projection = workout.get("write_projection")
    steps = _expanded_steps(projection.get("steps")) if isinstance(projection, dict) else []
    if not steps or len(steps) != len(laps):
        return {
            "state": "ambiguous",
            "reason": "lap_structure_mismatch",
            "planned_steps": len(steps),
            "actual_laps": len(laps),
        }
    intervals: list[dict[str, Any]] = []
    zones_by_number = {row.get("zone"): row for row in hr_zones}
    for index, (step, lap) in enumerate(zip(steps, laps, strict=True), start=1):
        if step.get("type") not in {"interval", "recovery"}:
            continue
        target = step.get("target")
        raw_type = target.get("type") if isinstance(target, dict) else None
        target_type = _TARGET_NAMES.get(raw_type) if isinstance(raw_type, str) else None
        row: dict[str, Any] = {
            "step_index": index,
            "step_type": step.get("type"),
            "lap_index": lap.get("lap_index"),
            "target_type": target_type,
            "quality": "lap_summary",
        }
        if target_type is None or not isinstance(target, dict):
            intervals.append({**row, "state": "not_targeted", "in_band": None})
            continue
        prescribed, low, high, high_inclusive = _band(target, target_type, zones_by_number, power_zones or [])
        value = _lap_value(lap, target_type)
        row["prescribed_band"] = prescribed
        if low is None or high is None:
            intervals.append({
                **row,
                "state": "insufficient_data",
                "in_band": None,
                "reason": (
                    power_zone_reason
                    if power_zone_reason and target_type == "power" and "zone" in target
                    else _boundary_reason(target_type)
                ),
            })
        elif value is None:
            intervals.append({
                **row,
                "state": "insufficient_data",
                "in_band": None,
                "reason": f"missing_{target_type}_sensor_data",
            })
        else:
            intervals.append({
                **row,
                "state": "completed",
                "in_band": _in_band(value, low, high, high_inclusive),
            })
    return {"state": "mapped", "intervals": intervals}
