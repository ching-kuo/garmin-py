"""Metric registry: declarative source-of-truth for all activity metrics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from garmin_cli.units import to_km as _to_km
from garmin_cli.units import to_kmh as _to_kmh
from garmin_cli.units import to_minutes as _to_minutes


# Sport typeKey families. These mirror the values Garmin Connect emits in
# ``activityType.typeKey``.
RUNNING_TYPE_KEYS: frozenset[str] = frozenset({
    "running",
    "trail_running",
    "treadmill_running",
    "track_running",
    "indoor_running",
})
CYCLING_TYPE_KEYS: frozenset[str] = frozenset({
    "cycling",
    "road_biking",
    "mountain_biking",
    "gravel_cycling",
    "virtual_ride",
    "indoor_cycling",
    "ebike_mountain_biking",
    "cyclocross",
})
LAP_SWIM_TYPE_KEYS: frozenset[str] = frozenset({"lap_swimming"})
OW_SWIM_TYPE_KEYS: frozenset[str] = frozenset({"open_water_swimming", "swimming"})
SWIM_TYPE_KEYS: frozenset[str] = LAP_SWIM_TYPE_KEYS | OW_SWIM_TYPE_KEYS


@dataclass(frozen=True)
class MetricEntry:
    """Declarative definition of a single metric.

    ``key`` is the existing serializer output key (e.g. ``avg_power_w``); Garmin
    wire names live only inside ``source_paths``. ``sports=None`` marks a
    universal metric. ``formatter`` is applied only when the resolved value is
    not None.
    """

    key: str
    source_paths: tuple[tuple[str, ...], ...]
    sports: frozenset[str] | None
    formatter: Callable[[Any], Any] | None = None


# --- Resolver helpers --------------------------------------------------------


def _walk(value: Any, path: tuple[str, ...]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def resolve(
    entry: MetricEntry,
    activity: dict[str, Any],
    summary_dto: dict[str, Any] | None = None,
) -> Any:
    """Resolve a metric value from an activity payload.

    Walks ``entry.source_paths`` in declared precedence and returns the first
    non-None value (after applying ``entry.formatter``). When ``summary_dto`` is
    passed separately, paths beginning with ``"summaryDTO"`` are tried against
    it first so callers that have already unpacked ``summaryDTO`` need not
    re-nest it.
    """
    for path in entry.source_paths:
        if summary_dto is not None and path and path[0] == "summaryDTO":
            value = _walk(summary_dto, path[1:])
            if value is not None:
                return entry.formatter(value) if entry.formatter else value
        value = _walk(activity, path)
        if value is not None:
            return entry.formatter(value) if entry.formatter else value
    return None


# --- Value transforms (preserve existing serializer semantics) ---------------
# Canonical converters live in ``garmin_cli.units``; the private aliases above
# keep the formatter references below readable.


# --- Registry entries --------------------------------------------------------


_ENTRIES: tuple[MetricEntry, ...] = (
    # --- Summary base fields -------------------------------------------------
    MetricEntry(
        key="id",
        source_paths=(("activityId",),),
        sports=None,
    ),
    MetricEntry(
        key="date",
        source_paths=(
            ("startTimeLocal",),
            ("summaryDTO", "startTimeLocal"),
        ),
        sports=None,
    ),
    MetricEntry(
        key="name",
        source_paths=(("activityName",),),
        sports=None,
    ),
    MetricEntry(
        key="type",
        source_paths=(("activityType", "typeKey"),),
        sports=None,
    ),
    MetricEntry(
        key="distance_km",
        source_paths=(
            ("distance",),
            ("summaryDTO", "distance"),
        ),
        sports=None,
        formatter=_to_km,
    ),
    MetricEntry(
        key="duration_min",
        source_paths=(
            ("duration",),
            ("summaryDTO", "duration"),
        ),
        sports=None,
        formatter=_to_minutes,
    ),
    MetricEntry(
        key="avg_hr",
        source_paths=(
            ("averageHR",),
            ("summaryDTO", "averageHR"),
        ),
        sports=None,
    ),
    # --- Detail fields, universal -------------------------------------------
    MetricEntry(
        key="max_hr",
        source_paths=(
            ("maxHR",),
            ("summaryDTO", "maxHR"),
        ),
        sports=None,
    ),
    MetricEntry(
        key="calories",
        source_paths=(
            ("calories",),
            ("summaryDTO", "calories"),
        ),
        sports=None,
    ),
    MetricEntry(
        key="elevation_gain_m",
        source_paths=(
            ("elevationGain",),
            ("summaryDTO", "elevationGain"),
        ),
        sports=None,
    ),
    MetricEntry(
        key="elevation_loss_m",
        source_paths=(
            ("elevationLoss",),
            ("summaryDTO", "elevationLoss"),
        ),
        sports=None,
    ),
    MetricEntry(
        key="avg_speed_kmh",
        source_paths=(
            ("averageSpeed",),
            ("summaryDTO", "averageSpeed"),
        ),
        sports=None,
        formatter=_to_kmh,
    ),
    MetricEntry(
        key="max_speed_kmh",
        source_paths=(
            ("maxSpeed",),
            ("summaryDTO", "maxSpeed"),
        ),
        sports=None,
        formatter=_to_kmh,
    ),
    # --- Running-specific ---------------------------------------------------
    MetricEntry(
        key="avg_cadence_spm",
        source_paths=(
            ("averageRunningCadenceInStepsPerMinute",),
            ("summaryDTO", "averageRunningCadenceInStepsPerMinute"),
        ),
        sports=RUNNING_TYPE_KEYS,
    ),
    MetricEntry(
        key="avg_ground_contact_time",
        source_paths=(
            ("avgGroundContactTime",),
            ("summaryDTO", "avgGroundContactTime"),
        ),
        sports=RUNNING_TYPE_KEYS,
    ),
    MetricEntry(
        key="avg_vertical_oscillation",
        source_paths=(
            ("avgVerticalOscillation",),
            ("summaryDTO", "avgVerticalOscillation"),
        ),
        sports=RUNNING_TYPE_KEYS,
    ),
    MetricEntry(
        key="avg_vertical_ratio",
        source_paths=(
            ("avgVerticalRatio",),
            ("summaryDTO", "avgVerticalRatio"),
        ),
        sports=RUNNING_TYPE_KEYS,
    ),
    MetricEntry(
        key="avg_stride_length",
        source_paths=(
            ("avgStrideLength",),
            ("summaryDTO", "avgStrideLength"),
        ),
        sports=RUNNING_TYPE_KEYS,
    ),
    # --- Cycling-specific ---------------------------------------------------
    MetricEntry(
        key="avg_cadence_rpm",
        source_paths=(
            ("averageBikingCadenceInRevPerMinute",),
            ("summaryDTO", "averageBikingCadenceInRevPerMinute"),
        ),
        sports=CYCLING_TYPE_KEYS,
    ),
    MetricEntry(
        key="avg_power_w",
        source_paths=(
            ("averagePower",),
            ("summaryDTO", "averagePower"),
        ),
        sports=CYCLING_TYPE_KEYS,
    ),
    MetricEntry(
        key="max_power_w",
        source_paths=(
            ("maxPower",),
            ("summaryDTO", "maxPower"),
        ),
        sports=CYCLING_TYPE_KEYS,
    ),
    MetricEntry(
        key="norm_power_w",
        source_paths=(
            ("normPower",),
            ("normalizedPower",),
            ("summaryDTO", "normPower"),
            ("summaryDTO", "normalizedPower"),
        ),
        sports=CYCLING_TYPE_KEYS,
    ),
    MetricEntry(
        key="tss",
        source_paths=(
            ("trainingStressScore",),
            ("summaryDTO", "trainingStressScore"),
        ),
        sports=CYCLING_TYPE_KEYS,
    ),
    MetricEntry(
        key="intensity_factor",
        source_paths=(
            ("intensityFactor",),
            ("summaryDTO", "intensityFactor"),
        ),
        sports=CYCLING_TYPE_KEYS,
    ),
    # --- Run/bike training response -----------------------------------------
    MetricEntry(
        key="aerobic_training_effect",
        source_paths=(
            ("aerobicTrainingEffect",),
            ("summaryDTO", "aerobicTrainingEffect"),
        ),
        sports=RUNNING_TYPE_KEYS | CYCLING_TYPE_KEYS,
    ),
    MetricEntry(
        key="anaerobic_training_effect",
        source_paths=(
            ("anaerobicTrainingEffect",),
            ("summaryDTO", "anaerobicTrainingEffect"),
        ),
        sports=RUNNING_TYPE_KEYS | CYCLING_TYPE_KEYS,
    ),
    MetricEntry(
        key="vo2max",
        source_paths=(
            ("vO2MaxValue",),
            ("summaryDTO", "vO2MaxValue"),
        ),
        sports=RUNNING_TYPE_KEYS | CYCLING_TYPE_KEYS,
    ),
    MetricEntry(
        key="recovery_time_h",
        source_paths=(
            ("recoveryTime",),
            ("summaryDTO", "recoveryTime"),
        ),
        sports=RUNNING_TYPE_KEYS | CYCLING_TYPE_KEYS,
        formatter=lambda minutes: None if minutes is None else minutes / 60,
    ),
    # --- Pool-swim aggregates -----------------------------------------------
    MetricEntry(
        key="swolf",
        source_paths=(
            ("avgSwolf",),
            ("summaryDTO", "avgSwolf"),
        ),
        sports=LAP_SWIM_TYPE_KEYS,
    ),
    MetricEntry(
        key="total_strokes",
        source_paths=(
            ("strokes",),
            ("summaryDTO", "strokes"),
            ("totalNumberOfStrokes",),
            ("summaryDTO", "totalNumberOfStrokes"),
        ),
        sports=LAP_SWIM_TYPE_KEYS,
    ),
    MetricEntry(
        key="avg_stroke_rate",
        source_paths=(
            ("averageStrokeRate",),
            ("summaryDTO", "averageStrokeRate"),
            ("avgStrokeRate",),
            ("summaryDTO", "avgStrokeRate"),
        ),
        sports=LAP_SWIM_TYPE_KEYS,
    ),
    MetricEntry(
        key="distance_per_stroke",
        source_paths=(
            ("avgStrokeDistance",),
            ("summaryDTO", "avgStrokeDistance"),
        ),
        sports=LAP_SWIM_TYPE_KEYS,
    ),
)


REGISTRY: Mapping[str, MetricEntry] = {entry.key: entry for entry in _ENTRIES}


def for_sport(type_key: str | None) -> Iterable[MetricEntry]:
    """Yield entries applicable to the given sport ``typeKey``.

    Entries with ``sports=None`` are universal and always yielded. When
    ``type_key`` is None or unknown, only universal entries are yielded.
    """
    for entry in _ENTRIES:
        if entry.sports is None or (type_key is not None and type_key in entry.sports):
            yield entry
