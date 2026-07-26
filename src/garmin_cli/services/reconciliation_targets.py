"""Pure target-comparison helpers for planned-versus-actual reconciliation."""
from __future__ import annotations

from typing import Any

from garmin_cli.metrics.registry import CYCLING_TYPE_KEYS, RUNNING_TYPE_KEYS
from garmin_cli.services.reconciliation_intervals import (
    _TARGET_NAMES,
    _expanded_steps,
    _lap_cadence,
    _lap_value,
    _number,
    compare_interval_completion,
)

SUPPORTED_SPORTS = RUNNING_TYPE_KEYS | CYCLING_TYPE_KEYS
_STREAM_KEYS = {
    "pace": ("directSpeed", "speed"),
    "power": ("directPower", "power"),
    "cadence": (
        "directRunCadence",
        "directRunningCadence",
        "directBikeCadence",
        "directCadence",
        "cadence",
    ),
}


def _pct(numerator: float, denominator: float) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator > 0 else 0.0


def _target_specs(workout: dict[str, Any]) -> list[dict[str, Any]]:
    projection = workout.get("write_projection")
    if not isinstance(projection, dict):
        return []
    specs: list[dict[str, Any]] = []
    expanded = _expanded_steps(projection.get("steps"))
    by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    for step_index, step in enumerate(expanded):
        target = step.get("target")
        if not isinstance(target, dict):
            continue
        raw_target_type = target.get("type")
        target_name = (
            _TARGET_NAMES.get(raw_target_type)
            if isinstance(raw_target_type, str)
            else None
        )
        if target_name is None:
            continue
        if "zone" in target:
            band = {"zone": target.get("zone")}
            identity: tuple[Any, ...] = (target_name, "zone", target.get("zone"))
        else:
            band = {"min": target.get("min"), "max": target.get("max")}
            identity = (target_name, "range", target.get("min"), target.get("max"))
        if identity in by_identity:
            by_identity[identity]["step_indexes"].append(step_index)
            continue
        duration = step.get("duration")
        spec = {
            "target_type": target_name,
            "prescribed_band": band,
            "weight_basis": (
                "distance"
                if isinstance(duration, dict) and duration.get("type") == "distance"
                else "time"
            ),
            "step_indexes": [step_index],
            "planned_step_count": len(expanded),
        }
        specs.append(spec)
        by_identity[identity] = spec
    return specs


def required_stream_metrics(
    workout: dict[str, Any],
    laps: list[dict[str, Any]],
) -> tuple[str, ...]:
    """Return sample-stream keys needed when lap summaries lack target metrics."""
    required: list[str] = []
    for spec in _target_specs(workout):
        target_type = spec["target_type"]
        if target_type == "pace":
            usable = any(
                (_number(row.get("distance_km")) or 0) > 0
                and (_number(row.get("duration_min")) or 0) > 0
                for row in laps
            )
            if not usable:
                required.append("directSpeed")
        elif target_type == "power":
            # Garmin power-zone write projections do not expose zone
            # boundaries, so a stream cannot make that prescription numeric.
            if "min" in spec["prescribed_band"] and not any(
                _number(row.get("avg_power_w")) is not None for row in laps
            ):
                required.append("directPower")
        elif target_type == "cadence" and not any(
            _lap_cadence(row) is not None for row in laps
        ):
            required.append(
                "directRunCadence"
                if workout.get("sport") in RUNNING_TYPE_KEYS
                else "directBikeCadence"
            )
    return tuple(dict.fromkeys(required))


def _band_result(
    spec: dict[str, Any],
    values: list[tuple[float | None, float]],
    *,
    quality: str,
    missing_reason: str,
    weight_basis: str | None = None,
) -> dict[str, Any]:
    band = spec["prescribed_band"]
    low = _number(band.get("min"))
    high = _number(band.get("max"))
    pct_key = (
        "distance_in_band_pct"
        if (weight_basis or spec["weight_basis"]) == "distance"
        else "time_in_band_pct"
    )
    base = {
        "target_type": spec["target_type"],
        "prescribed_band": band,
        pct_key: None,
        "coverage_pct": 0.0,
        "quality": quality,
    }
    if low is None or high is None:
        # The prescription itself has no numeric bounds (zone-based target),
        # which is a different failure than absent sensor data.
        target_type = spec["target_type"]
        boundary_reason = (
            "missing_power_zone_boundaries"
            if target_type == "power"
            else f"missing_{target_type}_target_boundaries"
        )
        return {**base, "state": "insufficient_data", "reason": boundary_reason}
    total_weight = sum(weight for _, weight in values if weight > 0)
    covered = [(value, weight) for value, weight in values if value is not None and weight > 0]
    covered_weight = sum(weight for _, weight in covered)
    if covered_weight <= 0:
        return {**base, "state": "insufficient_data", "reason": missing_reason}
    inside_weight = sum(
        weight for value, weight in covered if value is not None and low <= value <= high
    )
    return {
        **base,
        pct_key: _pct(inside_weight, covered_weight),
        "coverage_pct": _pct(covered_weight, total_weight),
        "state": "completed",
    }


def _hr_result(
    spec: dict[str, Any],
    hr_zones: list[dict[str, Any]],
) -> dict[str, Any]:
    band = spec["prescribed_band"]
    zone = band.get("zone")
    total = sum(_number(row.get("seconds_in_zone")) or 0.0 for row in hr_zones)
    base = {
        "target_type": "hr",
        "prescribed_band": band,
        "time_in_band_pct": None,
        "coverage_pct": 0.0,
        "quality": "hr_zone_summary",
    }
    if total <= 0:
        return {
            **base,
            "state": "insufficient_data",
            "reason": "missing_hr_sensor_data",
        }
    inside = sum(
        _number(row.get("seconds_in_zone")) or 0.0
        for row in hr_zones
        if row.get("zone") == zone
    )
    return {
        **base,
        "time_in_band_pct": _pct(inside, total),
        "coverage_pct": 100.0,
        "state": "completed",
    }


def _sample_values(
    rows: list[dict[str, Any]],
    target_type: str,
) -> list[tuple[float | None, float]]:
    keys = _STREAM_KEYS[target_type]
    values: list[tuple[float | None, float]] = []
    for row in rows:
        value = next(
            (
                parsed
                for key in keys
                if (parsed := _number(row.get(key))) is not None
            ),
            None,
        )
        values.append((value, 1.0))
    return values


def _lap_values(
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> list[tuple[float | None, float]]:
    weight_key = "distance_km" if spec["weight_basis"] == "distance" else "duration_min"
    selected = rows
    if len(rows) == spec["planned_step_count"]:
        selected = [
            rows[index]
            for index in spec["step_indexes"]
            if index < len(rows)
        ]
    return [
        (_lap_value(row, spec["target_type"]), _number(row.get(weight_key)) or 0.0)
        for row in selected
    ]


def compare_activity_targets(
    *,
    sport: Any,
    workout: dict[str, Any],
    laps: list[dict[str, Any]],
    hr_zones: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    stream_unavailable_reason: str | None = None,
) -> dict[str, Any]:
    """Compare supported workout targets using zones, laps, then samples."""
    if sport not in SUPPORTED_SPORTS:
        return {
            "state": "insufficient_data",
            "reason": "unsupported_sport",
            "targets": [],
            "data_quality": [{"reason": "unsupported_sport"}],
        }
    specs = _target_specs(workout)
    if not specs:
        return {
            "state": "insufficient_data",
            "reason": "no_supported_targets",
            "targets": [],
            "data_quality": [{"reason": "no_supported_targets"}],
        }

    targets: list[dict[str, Any]] = []
    for spec in specs:
        target_type = spec["target_type"]
        if target_type == "hr":
            targets.append(_hr_result(spec, hr_zones))
            continue
        if target_type == "power" and "zone" in spec["prescribed_band"]:
            targets.append(_band_result(
                spec,
                [],
                quality="unavailable",
                missing_reason="missing_power_zone_boundaries",
            ))
            continue
        lap_values = _lap_values(laps, spec)
        if any(value is not None and weight > 0 for value, weight in lap_values):
            # When the lap structure does not match the plan, per-step laps
            # cannot be attributed to this target; the score is a whole-
            # activity aggregate and must say so.
            lap_quality = (
                "lap_summary"
                if len(laps) == spec["planned_step_count"]
                else "lap_summary_aggregate"
            )
            targets.append(_band_result(
                spec,
                lap_values,
                quality=lap_quality,
                missing_reason=f"missing_{target_type}_sensor_data",
            ))
            continue
        reason = stream_unavailable_reason or f"missing_{target_type}_sensor_data"
        # Samples carry equal weights (fixed recording interval), so the score
        # is time-weighted regardless of how the step was prescribed.
        targets.append(_band_result(
            spec,
            _sample_values(samples, target_type),
            quality="sampled_stream" if samples else "unavailable",
            missing_reason=reason,
            weight_basis="time",
        ))

    insufficient = [
        {"target_type": target["target_type"], "reason": target["reason"]}
        for target in targets
        if target["state"] == "insufficient_data"
    ]
    interval_mapping = compare_interval_completion(workout, laps, hr_zones)
    data_quality = list(insufficient)
    if interval_mapping["state"] == "ambiguous":
        data_quality.append({"reason": interval_mapping["reason"]})
    return {
        "state": "insufficient_data" if insufficient else "completed",
        "targets": targets,
        "interval_mapping": interval_mapping,
        "data_quality": data_quality,
    }
