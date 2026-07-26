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


def _band(
    target: dict[str, Any],
    target_type: str,
    hr_zones: list[dict[str, Any]],
) -> tuple[dict[str, Any], float | None, float | None]:
    if "zone" not in target:
        prescribed = {"min": target.get("min"), "max": target.get("max")}
        return prescribed, _number(target.get("min")), _number(target.get("max"))
    prescribed = {"zone": target.get("zone")}
    if target_type != "hr":
        return prescribed, None, None
    row = next(
        (zone for zone in hr_zones if zone.get("zone") == target.get("zone")),
        {},
    )
    return (
        prescribed,
        _number(row.get("zone_low_bpm")),
        _number(row.get("zone_high_bpm")),
    )


def compare_interval_completion(
    workout: dict[str, Any],
    laps: list[dict[str, Any]],
    hr_zones: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map laps only when the expanded workout and lap counts match exactly."""
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
        prescribed, low, high = _band(target, target_type, hr_zones)
        value = _lap_value(lap, target_type)
        row["prescribed_band"] = prescribed
        if low is None or high is None:
            reason = (
                "missing_power_zone_boundaries"
                if target_type == "power"
                else f"missing_{target_type}_target_boundaries"
            )
            intervals.append({
                **row,
                "state": "insufficient_data",
                "in_band": None,
                "reason": reason,
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
                "in_band": low <= value <= high,
            })
    return {"state": "mapped", "intervals": intervals}
