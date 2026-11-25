"""Pure target-comparison helpers for planned-versus-actual reconciliation."""
from __future__ import annotations

import statistics
from typing import Any

from garmin_cli.metrics.registry import CYCLING_TYPE_KEYS, RUNNING_TYPE_KEYS
from garmin_cli.services.reconciliation_intervals import (
    _TARGET_NAMES,
    _band,
    _boundary_reason,
    _expanded_steps,
    _in_band,
    _lap_value,
    _number,
    compare_interval_completion,
    power_zone_bounds,
)

SUPPORTED_SPORTS = RUNNING_TYPE_KEYS | CYCLING_TYPE_KEYS
# Stream keys in preference order. Live running streams carry
# directDoubleCadence in full steps/min (matching the summary and workout
# cadence targets) and directRunCadence per foot, about half of that.
_STREAM_KEYS: dict[str, tuple[str, ...]] = {
    "pace": ("directSpeed", "speed"),
    "power": ("directPower", "power"),
    "cadence": (
        "directDoubleCadence",
        "directRunCadence",
        "directRunningCadence",
        "directBikeCadence",
        "directCadence",
        "cadence",
    ),
    "hr": ("directHeartRate",),
}
_PER_FOOT_MEDIAN_LIMIT = 120.0


def _run_cadence_scale(rows: list[dict[str, Any]]) -> float:
    """2.0 when the directRunCadence stream looks per-foot, else 1.0.

    shortcut: both cadence descriptors say stepsPerMinute, so the unit cannot be
    read from the payload; live per-foot medians are ~88 and running step rates
    are rarely under 120, so a median below 120 is taken as per-foot. Upgrade
    when Garmin exposes the unit.
    """
    values = [value for row in rows if (value := _number(row.get("directRunCadence"))) is not None]
    return 2.0 if values and statistics.median(values) < _PER_FOOT_MEDIAN_LIMIT else 1.0


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
        duration = step.get("duration")
        weight_basis = (
            "distance" if isinstance(duration, dict) and duration.get("type") == "distance" else "time"
        )
        # Timed and distance steps with the same band are weighted differently.
        if "zone" in target:
            band = {"zone": target.get("zone")}
            identity: tuple[Any, ...] = (target_name, weight_basis, "zone", target.get("zone"))
        else:
            band = {"min": target.get("min"), "max": target.get("max")}
            identity = (target_name, weight_basis, "range", target.get("min"), target.get("max"))
        if identity in by_identity:
            by_identity[identity]["step_indexes"].append(step_index)
            continue
        spec = {
            "target_type": target_name,
            "prescribed_band": band,
            "weight_basis": weight_basis,
            "step_indexes": [step_index],
            "planned_step_count": len(expanded),
        }
        specs.append(spec)
        by_identity[identity] = spec
    return specs


Bounds = tuple[float, float, bool]


def _spec_bounds(spec: dict[str, Any], power_zones: list[dict[str, Any]]) -> Bounds | None:
    """(low, high, high inclusive) of a non-HR-zone spec, or None when not numeric."""
    _, low, high, inclusive = _band(spec["prescribed_band"], spec["target_type"], {}, power_zones)
    return None if low is None or high is None else (low, high, inclusive)


def _has_lap_values(laps: list[dict[str, Any]], spec: dict[str, Any]) -> bool:
    return any(value is not None and weight > 0 for value, weight in _lap_values(laps, spec))


def required_stream_metrics(
    workout: dict[str, Any],
    laps: list[dict[str, Any]],
    power_zones: list[dict[str, Any]] | None = None,
) -> tuple[str, ...]:
    """Return sample-stream keys needed when lap summaries lack target metrics.

    Uses the same lap selection as :func:`compare_activity_targets`, and skips
    targets with no numeric band (an unresolved power zone) or scored from the
    HR time-in-zone summary (an HR zone number).
    """
    required: list[str] = []
    zones = _workout_power_zones(workout, power_zones)
    for spec in _target_specs(workout):
        target_type = spec["target_type"]
        if target_type == "hr" and "zone" in spec["prescribed_band"]:
            continue
        if _spec_bounds(spec, zones) is None or _has_lap_values(laps, spec):
            continue
        if target_type == "cadence":
            required.append(
                "directDoubleCadence" if workout.get("sport") in RUNNING_TYPE_KEYS else "directBikeCadence"
            )
        else:
            required.append(_STREAM_KEYS[target_type][0])
    return tuple(dict.fromkeys(required))


def _power_zone_sport_key(sport: Any) -> str | None:
    if sport in RUNNING_TYPE_KEYS:
        return "RUNNING"
    return "CYCLING" if sport in CYCLING_TYPE_KEYS else None


def _workout_power_zones(workout: dict[str, Any], power_zones: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Only the rows of the workout sport's power zone table, so cycling watts never score a run."""
    key = _power_zone_sport_key(workout.get("sport"))
    return [row for row in power_zones or [] if key is not None and row.get("sport") == key.lower()]


def power_zone_sport(workout: dict[str, Any], sport: Any) -> str | None:
    """Garmin power-zone sport key to fetch for *workout* done as a *sport* activity.

    None unless the workout has a power zone-number target and the workout's
    sport and the activity's sport share a power zone table.
    """
    if not any(
        spec["target_type"] == "power" and "zone" in spec["prescribed_band"]
        for spec in _target_specs(workout)
    ):
        return None
    key = _power_zone_sport_key(workout.get("sport"))
    return key if key is not None and key == _power_zone_sport_key(sport) else None


def _band_result(
    spec: dict[str, Any],
    values: list[tuple[float | None, float]],
    bounds: Bounds | None,
    *,
    quality: str,
    missing_reason: str,
    weight_basis: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Score *values* against *bounds*; None bounds means the band is not numeric."""
    pct_key = (
        "distance_in_band_pct"
        if (weight_basis or spec["weight_basis"]) == "distance"
        else "time_in_band_pct"
    )
    base = {
        "target_type": spec["target_type"],
        "prescribed_band": spec["prescribed_band"],
        **({"resolved_band": spec["resolved_band"]} if "resolved_band" in spec else {}),
        pct_key: None,
        "coverage_pct": 0.0,
        "quality": quality,
    }
    total_weight = sum(weight for _, weight in values if weight > 0)
    covered = [(value, weight) for value, weight in values if value is not None and weight > 0]
    covered_weight = sum(weight for _, weight in covered)
    if bounds is None or covered_weight <= 0:
        return {**base, "state": "insufficient_data", "reason": missing_reason}
    inside_weight = sum(
        weight for value, weight in covered if value is not None and _in_band(value, *bounds)
    )
    return {
        **base,
        pct_key: _pct(inside_weight, covered_weight),
        "coverage_pct": _pct(covered_weight, total_weight),
        "state": "completed",
        # Only a score actually computed from samples carries its scope.
        **({"scope": scope} if scope else {}),
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
    scales = {"directRunCadence": _run_cadence_scale(rows)} if target_type == "cadence" else {}
    values: list[tuple[float | None, float]] = []
    for row in rows:
        value = next(
            (
                parsed * scales.get(key, 1.0)
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
    power_zones: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare supported workout targets using zones, laps, then samples.

    *power_zones* are the athlete's serialized power zone rows for the
    workout's sport; they turn power zone-number targets into watt bands. A
    sample-stream score covers the whole activity (``scope``), since streams
    are only used when laps cannot attribute values to steps.
    """
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

    # A running workout's power zones do not describe a ride, and vice versa;
    # a workout sport without a power zone table cannot resolve a zone number.
    workout_key = _power_zone_sport_key(workout.get("sport"))
    power_reason = (
        "power_zone_sport_unsupported"
        if workout_key is None
        else "power_zone_sport_mismatch" if workout_key != _power_zone_sport_key(sport) else None
    )
    zones = [] if power_reason else _workout_power_zones(workout, power_zones)
    targets: list[dict[str, Any]] = []
    for spec in specs:
        target_type = spec["target_type"]
        band = spec["prescribed_band"]
        if target_type == "hr" and "zone" in band:
            targets.append(_hr_result(spec, hr_zones))
            continue
        if target_type == "power" and "zone" in band:
            resolved = power_zone_bounds(band["zone"], zones)
            if resolved is not None:
                spec = {**spec, "resolved_band": resolved}
        bounds = _spec_bounds(spec, zones)
        if bounds is None:
            # The prescription itself has no numeric bounds, which is a
            # different failure than absent sensor data.
            reason = (
                power_reason
                if power_reason and target_type == "power" and "zone" in band
                else _boundary_reason(target_type)
            )
            targets.append(_band_result(spec, [], None, quality="unavailable", missing_reason=reason))
            continue
        lap_values = _lap_values(laps, spec)
        if _has_lap_values(laps, spec):
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
                bounds,
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
            bounds,
            quality="sampled_stream" if samples else "unavailable",
            missing_reason=reason,
            weight_basis="time",
            scope="whole_activity",
        ))

    insufficient = [
        {"target_type": target["target_type"], "reason": target["reason"]}
        for target in targets
        if target["state"] == "insufficient_data"
    ]
    interval_mapping = compare_interval_completion(workout, laps, hr_zones, zones, power_reason)
    data_quality = list(insufficient)
    if interval_mapping["state"] == "ambiguous":
        data_quality.append({"reason": interval_mapping["reason"]})
    return {
        "state": "insufficient_data" if insufficient else "completed",
        "targets": targets,
        "interval_mapping": interval_mapping,
        "data_quality": data_quality,
    }
