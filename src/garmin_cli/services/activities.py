"""Activity service helpers shared by the CLI and MCP front-ends.

These functions own the two pieces of activity logic that were previously
copy-pasted between :mod:`garmin_cli.commands.activities` and
:mod:`garmin_cli.mcp_server`:

* the multisport laps fan-out (fetch laps for an activity, fanning out to
  child legs for multisport parents and stamping a 0-based ``leg_index``), and
* capability-manifest assembly for an activity's detail projection.

Endpoint and serializer callables are injected rather than imported directly.
Each front-end module re-exports the relevant Garmin endpoint names (e.g.
``get_activity_splits``) at module scope and the test suites monkeypatch those
re-exports. Passing the front-end's own references through keeps those patch
targets effective while the algorithm lives in exactly one place.
"""
from __future__ import annotations

from typing import Any, Callable

from garmin_cli.metrics.registry import LAP_SWIM_TYPE_KEYS
from garmin_cli.metrics.sport_profile import SportProfile, profile_for

# Injected endpoint/serializer callable aliases. The concrete callables are
# supplied by the caller so that per-front-end monkeypatching still applies.
SplitsFn = Callable[[Any], Any]
TypedSplitsFn = Callable[[Any], Any]
ChildrenFn = Callable[[dict[str, Any]], list[dict[str, Any]]]
IsMultisportFn = Callable[[dict[str, Any]], bool]
ActivityTypeKeyFn = Callable[[dict[str, Any]], str | None]
SerializeLapsFn = Callable[[dict[str, Any], Any, SportProfile], list[dict[str, Any]]]
SerializeDetailFn = Callable[[dict[str, Any]], list[dict[str, Any]]]
SerializeManifestFn = Callable[..., list[dict[str, Any]]]


def fetch_one_activity_laps(
    activity: dict[str, Any],
    activity_id: Any,
    *,
    activity_type_key: ActivityTypeKeyFn,
    splits_fn: SplitsFn,
    typed_splits_fn: TypedSplitsFn,
    serialize_laps: SerializeLapsFn,
) -> tuple[list[dict[str, Any]], SportProfile]:
    """Fetch laps for a single (non-multisport) activity, auto-routing by sport.

    Pool-swim activities use the typed-splits endpoint to get per-pool-length
    rows; everything else uses the raw-URL splits endpoint. Returns the
    serialized rows together with the resolved :class:`SportProfile` (the CLI
    uses the profile to pick table columns; the MCP front-end ignores it).
    """
    profile = profile_for(activity_type_key(activity))
    if profile.type_keys & LAP_SWIM_TYPE_KEYS:
        splits_payload = typed_splits_fn(activity_id)
    else:
        splits_payload = splits_fn(activity_id)
    rows = serialize_laps(activity, splits_payload, profile)
    return rows, profile


def fetch_laps_for_activity(
    activity: dict[str, Any],
    activity_id: Any,
    *,
    activity_type_key: ActivityTypeKeyFn,
    is_multisport_parent: IsMultisportFn,
    get_multisport_children: ChildrenFn,
    splits_fn: SplitsFn,
    typed_splits_fn: TypedSplitsFn,
    serialize_laps: SerializeLapsFn,
) -> tuple[list[dict[str, Any]], SportProfile]:
    """Fetch laps for an activity, handling multisport parents.

    For multisport parents, iterates child legs, fetches each child's laps, and
    stamps ``leg_index`` (0-based) onto every returned row. The returned profile
    is the parent's profile (for table column hints); per-row sport-specificity
    remains intact via the columns each row carries. Children whose
    ``activityId`` is missing are skipped.
    """
    if is_multisport_parent(activity):
        children = get_multisport_children(activity)
        if children:
            all_rows: list[dict[str, Any]] = []
            for idx, child in enumerate(children):
                child_id = child.get("activityId")
                if child_id is None:
                    continue
                child_rows, _ = fetch_one_activity_laps(
                    child,
                    child_id,
                    activity_type_key=activity_type_key,
                    splits_fn=splits_fn,
                    typed_splits_fn=typed_splits_fn,
                    serialize_laps=serialize_laps,
                )
                for row in child_rows:
                    row["leg_index"] = idx
                all_rows.extend(child_rows)
            return all_rows, profile_for(activity_type_key(activity))
    return fetch_one_activity_laps(
        activity,
        activity_id,
        activity_type_key=activity_type_key,
        splits_fn=splits_fn,
        typed_splits_fn=typed_splits_fn,
        serialize_laps=serialize_laps,
    )


def build_capability_manifest(
    activity: dict[str, Any],
    rows: list[dict[str, Any]],
    children: list[dict[str, Any]],
    *,
    serialize_detail: SerializeDetailFn,
    serialize_manifest: SerializeManifestFn,
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
            child_row = serialize_detail(child)
            child_projected = child_row[0] if child_row else None
            manifest.extend(
                serialize_manifest(child, child_projected, leg_index=idx)
            )
        return manifest
    projected = rows[0] if rows else None
    return serialize_manifest(activity, projected)
