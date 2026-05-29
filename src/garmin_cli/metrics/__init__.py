"""Declarative catalog of metric definitions.

The registry is the single source of truth for metric keys, source paths,
sport applicability, and formatting. CLI columns, MCP response fields, and
capability manifests all derive from registry entries.
"""
from __future__ import annotations

from garmin_cli.metrics.registry import (
    CYCLING_TYPE_KEYS,
    LAP_SWIM_TYPE_KEYS,
    OW_SWIM_TYPE_KEYS,
    REGISTRY,
    RUNNING_TYPE_KEYS,
    MetricEntry,
    for_sport,
    resolve,
)

__all__ = (
    "CYCLING_TYPE_KEYS",
    "LAP_SWIM_TYPE_KEYS",
    "OW_SWIM_TYPE_KEYS",
    "REGISTRY",
    "RUNNING_TYPE_KEYS",
    "MetricEntry",
    "for_sport",
    "resolve",
)
