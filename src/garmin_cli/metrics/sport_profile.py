"""Sport profiles: per-sport configuration of which metrics to project.

Each profile maps a family of typeKeys (e.g., running variants) to the
registry keys that make sense for that sport. ``profile_for(typeKey)``
returns the matching profile or ``DEFAULT_PROFILE`` for unknown sports.
"""
from __future__ import annotations

from dataclasses import dataclass

from garmin_cli.metrics.registry import (
    CYCLING_TYPE_KEYS,
    LAP_SWIM_TYPE_KEYS,
    OW_SWIM_TYPE_KEYS,
    REGISTRY,
    RUNNING_TYPE_KEYS,
)


@dataclass(frozen=True)
class SportProfile:
    """Per-sport projection plan for the activity-detail surface."""

    type_keys: frozenset[str]
    summary_metrics: tuple[str, ...]
    standard_metrics: tuple[str, ...]

    def detail_metrics(self) -> tuple[str, ...]:
        """Concatenated summary + standard keys (order preserved)."""
        return self.summary_metrics + self.standard_metrics


_BASE_SUMMARY_KEYS: tuple[str, ...] = (
    "id",
    "date",
    "name",
    "type",
    "distance_km",
    "duration_min",
    "avg_hr",
)


_UNIVERSAL_STANDARD_KEYS: tuple[str, ...] = (
    # Sport-aware tables surface elapsed time next to the other time fields for
    # readability; the CSV/JSON union (UNION_COLUMNS) instead appends it last to
    # preserve positional back-compat. Table and CSV column orders already
    # differ by design, so the placements diverge intentionally.
    "elapsed_time_min",
    "max_hr",
    "calories",
    "elevation_gain_m",
    "elevation_loss_m",
    "avg_speed_kmh",
    "max_speed_kmh",
    "training_effect_label",
    "training_load",
    "workout_id",
)


# Garmin emits training effect for swims (and other sports) too, so these two
# render for every profile; vo2max/recovery stay run/bike-only.
_TRAINING_EFFECT_KEYS: tuple[str, ...] = (
    "aerobic_training_effect",
    "anaerobic_training_effect",
)

_RUN_BIKE_TRAINING_RESPONSE: tuple[str, ...] = _TRAINING_EFFECT_KEYS + (
    "vo2max",
    "recovery_time_h",
)

# Sports without a sport-specific metric block (OWS, multisport, unknown).
_UNIVERSAL_WITH_TRAINING_EFFECT: tuple[str, ...] = (
    _UNIVERSAL_STANDARD_KEYS + _TRAINING_EFFECT_KEYS
)


CYCLING_PROFILE = SportProfile(
    type_keys=CYCLING_TYPE_KEYS,
    summary_metrics=_BASE_SUMMARY_KEYS,
    standard_metrics=_UNIVERSAL_STANDARD_KEYS + (
        "avg_cadence_rpm",
        "avg_power_w",
        "max_power_w",
        "norm_power_w",
        "tss",
        "intensity_factor",
    ) + _RUN_BIKE_TRAINING_RESPONSE,
)


RUNNING_PROFILE = SportProfile(
    type_keys=RUNNING_TYPE_KEYS,
    summary_metrics=_BASE_SUMMARY_KEYS,
    standard_metrics=_UNIVERSAL_STANDARD_KEYS + (
        "avg_cadence_spm",
        "avg_ground_contact_time",
        "avg_vertical_oscillation",
        "avg_vertical_ratio",
        "avg_stride_length",
    ) + _RUN_BIKE_TRAINING_RESPONSE,
)


LAP_SWIM_PROFILE = SportProfile(
    type_keys=LAP_SWIM_TYPE_KEYS,
    summary_metrics=_BASE_SUMMARY_KEYS,
    standard_metrics=_UNIVERSAL_STANDARD_KEYS + (
        "swolf",
        "total_strokes",
        "avg_stroke_rate",
        "distance_per_stroke",
    ) + _TRAINING_EFFECT_KEYS,
)


OPEN_WATER_SWIM_PROFILE = SportProfile(
    type_keys=OW_SWIM_TYPE_KEYS,
    summary_metrics=_BASE_SUMMARY_KEYS,
    # OWS has no per-length stroke aggregates and no SWOLF.
    standard_metrics=_UNIVERSAL_WITH_TRAINING_EFFECT,
)


MULTI_SPORT_PROFILE = SportProfile(
    type_keys=frozenset({"multi_sport", "multisport"}),
    summary_metrics=_BASE_SUMMARY_KEYS,
    standard_metrics=_UNIVERSAL_WITH_TRAINING_EFFECT,
)


DEFAULT_PROFILE = SportProfile(
    type_keys=frozenset(),
    summary_metrics=_BASE_SUMMARY_KEYS,
    standard_metrics=_UNIVERSAL_WITH_TRAINING_EFFECT,
)


PROFILES: tuple[SportProfile, ...] = (
    RUNNING_PROFILE,
    CYCLING_PROFILE,
    LAP_SWIM_PROFILE,
    OPEN_WATER_SWIM_PROFILE,
    MULTI_SPORT_PROFILE,
)


def profile_for(type_key: str | None) -> SportProfile:
    """Return the sport profile matching ``type_key`` or ``DEFAULT_PROFILE``."""
    if type_key is None:
        return DEFAULT_PROFILE
    for profile in PROFILES:
        if type_key in profile.type_keys:
            return profile
    return DEFAULT_PROFILE


# Stable union-schema column order for activity-detail output. Once published,
# ordering is back-compat critical: existing CSV pipelines must not see legacy
# columns reordered.
_LEGACY_DETAIL_ORDER: tuple[str, ...] = (
    "id",
    "date",
    "name",
    "type",
    "distance_km",
    "duration_min",
    "avg_hr",
    "max_hr",
    "calories",
    "elevation_gain_m",
    "elevation_loss_m",
    "avg_speed_kmh",
    "max_speed_kmh",
    "avg_cadence_spm",
    "avg_cadence_rpm",
    "avg_power_w",
    "max_power_w",
    "norm_power_w",
    "tss",
    "intensity_factor",
)

_RUNNING_APPENDED: tuple[str, ...] = (
    "avg_ground_contact_time",
    "avg_vertical_oscillation",
    "avg_vertical_ratio",
    "avg_stride_length",
)

_SWIM_APPENDED: tuple[str, ...] = (
    "swolf",
    "total_strokes",
    "avg_stroke_rate",
    "distance_per_stroke",
)

# Appended after the legacy/sport blocks so existing positional CSV consumers
# keep their column indices (new columns only ever land at the end).
_APPENDED_UNIVERSAL: tuple[str, ...] = (
    "elapsed_time_min",
    "training_effect_label",
    "training_load",
    "workout_id",
)


UNION_COLUMNS: tuple[str, ...] = (
    _LEGACY_DETAIL_ORDER
    + _RUNNING_APPENDED
    + _RUN_BIKE_TRAINING_RESPONSE
    + _SWIM_APPENDED
    + _APPENDED_UNIVERSAL
)


def columns_for_sport(type_key: str | None) -> tuple[str, ...]:
    """Return the table column order for ``type_key`` (sport-aware)."""
    return profile_for(type_key).detail_metrics()


def _validate_registry_coverage() -> None:
    for profile in PROFILES + (DEFAULT_PROFILE,):
        for key in profile.detail_metrics():
            if key not in REGISTRY:
                raise RuntimeError(
                    f"SportProfile references unknown metric key: {key!r}"
                )
    for key in UNION_COLUMNS:
        if key not in REGISTRY:
            raise RuntimeError(
                f"UNION_COLUMNS references unknown metric key: {key!r}"
            )
    # Universal keys are hand-listed twice: in the sport tables
    # (_UNIVERSAL_STANDARD_KEYS) and at the tail of the CSV union
    # (_APPENDED_UNIVERSAL). Catch a key added to one but not the other.
    appended_not_universal = set(_APPENDED_UNIVERSAL) - set(_UNIVERSAL_STANDARD_KEYS)
    if appended_not_universal:
        raise RuntimeError(
            "_APPENDED_UNIVERSAL keys missing from _UNIVERSAL_STANDARD_KEYS: "
            f"{sorted(appended_not_universal)!r}"
        )


_validate_registry_coverage()
