"""Activity service helpers shared by the CLI and MCP front-ends.

These functions own the two pieces of activity logic that were previously
copy-pasted between :mod:`garmin_cli.commands.activities` and
:mod:`garmin_cli.mcp_tools.activities`:

* the multisport laps fan-out (fetch laps for an activity, fanning out to
  child legs for multisport parents and stamping a 0-based ``leg_index``), and
* capability-manifest assembly for an activity's detail projection.
"""
from __future__ import annotations

import math
from typing import Any

from garmin_cli.endpoints.activities import (
    activity_type_key,
    get_activity_splits,
    get_activity_typed_splits,
    get_multisport_children,
    is_multisport_parent,
)
from garmin_cli.metrics.registry import LAP_SWIM_TYPE_KEYS
from garmin_cli.metrics.sport_profile import SportProfile, profile_for
from garmin_cli.serializers import (
    serialize_activity_detail,
    serialize_activity_laps,
    serialize_capability_manifest,
)


def downsample_rows(
    rows: list[dict[str, Any]],
    max_samples: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return a deterministic whole-stream stride sample and its stride."""
    if not rows:
        return [], 1
    stride = max(1, math.ceil(len(rows) / max_samples))
    return rows[::stride], stride


def fetch_one_activity_laps(
    activity: dict[str, Any],
    activity_id: Any,
) -> tuple[list[dict[str, Any]], SportProfile]:
    """Fetch laps for a single (non-multisport) activity, auto-routing by sport.

    Pool-swim activities use the typed-splits endpoint to get per-pool-length
    rows; everything else uses the raw-URL splits endpoint. Returns the
    serialized rows together with the resolved :class:`SportProfile` (the CLI
    uses the profile to pick table columns; the MCP front-end ignores it).
    """
    profile = profile_for(activity_type_key(activity))
    if profile.type_keys & LAP_SWIM_TYPE_KEYS:
        splits_payload = get_activity_typed_splits(activity_id)
    else:
        splits_payload = get_activity_splits(activity_id)
    rows = serialize_activity_laps(activity, splits_payload, profile)
    return rows, profile


def fetch_laps_for_activity(
    activity: dict[str, Any],
    activity_id: Any,
    children: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], SportProfile]:
    """Fetch laps for an activity, handling multisport parents.

    For multisport parents, iterates child legs, fetches each child's laps, and
    stamps ``leg_index`` (0-based) onto every returned row. The returned profile
    is the parent's profile (for table column hints); per-row sport-specificity
    remains intact via the columns each row carries. Children whose
    ``activityId`` is missing are skipped. If the caller already fetched the
    child list (e.g. to render it elsewhere in the same command), pass it as
    ``children`` to skip the redundant ``get_multisport_children`` call.
    """
    if is_multisport_parent(activity):
        if children is None:
            children = get_multisport_children(activity)
        if children:
            all_rows: list[dict[str, Any]] = []
            for idx, child in enumerate(children):
                child_id = child.get("activityId")
                if child_id is None:
                    continue
                child_rows, _ = fetch_one_activity_laps(child, child_id)
                for row in child_rows:
                    row["leg_index"] = idx
                all_rows.extend(child_rows)
            return all_rows, profile_for(activity_type_key(activity))
    return fetch_one_activity_laps(activity, activity_id)


def build_capability_manifest(
    activity: dict[str, Any],
    rows: list[dict[str, Any]],
    children: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble the capability manifest for an activity-detail projection.

    For a multisport parent (``children`` non-empty) the per-child manifests are
    unioned with a 0-based ``leg_index`` stamped on each entry. Otherwise the
    manifest is computed from the parent's own detail projection (``rows``).
    Returns an empty list when nothing is unavailable.
    """
    if children:
        manifest: list[dict[str, Any]] = []
        for idx, child in enumerate(children):
            child_row = serialize_activity_detail(child)
            child_projected = child_row[0] if child_row else None
            manifest.extend(
                serialize_capability_manifest(child, child_projected, leg_index=idx)
            )
        return manifest
    projected = rows[0] if rows else None
    return serialize_capability_manifest(activity, projected)
