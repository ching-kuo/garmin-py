"""Unit tests for the front-end-agnostic activity service layer.

These exercise :mod:`garmin_cli.services.activities` directly with injected
endpoint/serializer fakes, independent of the CLI and MCP front-ends. The
real :func:`profile_for` / ``LAP_SWIM_TYPE_KEYS`` routing is used (those are
not injected), so the swim-vs-raw split is verified end to end.
"""
from __future__ import annotations

from typing import Any

from garmin_cli.metrics.sport_profile import SportProfile
from garmin_cli.services.activities import (
    build_capability_manifest,
    fetch_laps_for_activity,
    fetch_one_activity_laps,
)


def _type_key(activity: dict[str, Any]) -> str | None:
    activity_type = activity.get("activityType")
    if isinstance(activity_type, dict):
        return activity_type.get("typeKey")
    return None


class _Recorder:
    """Records which splits endpoint each activity id was routed to."""

    def __init__(self) -> None:
        self.splits_calls: list[Any] = []
        self.typed_calls: list[Any] = []

    def splits(self, activity_id: Any) -> dict[str, Any]:
        self.splits_calls.append(activity_id)
        return {"lapDTOs": [{"id": activity_id, "src": "splits"}]}

    def typed(self, activity_id: Any) -> dict[str, Any]:
        self.typed_calls.append(activity_id)
        return {"lengthDTOs": [{"id": activity_id, "src": "typed"}]}


def _serialize_laps(
    activity: dict[str, Any], payload: Any, profile: SportProfile
) -> list[dict[str, Any]]:
    """Echo the payload rows so tests can assert which endpoint fed them."""
    rows = payload.get("lapDTOs") or payload.get("lengthDTOs") or []
    return [dict(row) for row in rows]


def _laps_kwargs(rec: _Recorder) -> dict[str, Any]:
    return {
        "activity_type_key": _type_key,
        "splits_fn": rec.splits,
        "typed_splits_fn": rec.typed,
        "serialize_laps": _serialize_laps,
    }


# ---------------------------------------------------------------------------
# fetch_one_activity_laps -- sport routing
# ---------------------------------------------------------------------------


class TestFetchOneActivityLaps:
    def test_running_routes_to_raw_splits(self) -> None:
        rec = _Recorder()
        activity = {"activityType": {"typeKey": "running"}}
        rows, profile = fetch_one_activity_laps(activity, 1, **_laps_kwargs(rec))
        assert rec.splits_calls == [1]
        assert rec.typed_calls == []
        assert rows == [{"id": 1, "src": "splits"}]
        assert isinstance(profile, SportProfile)

    def test_lap_swim_routes_to_typed_splits(self) -> None:
        rec = _Recorder()
        activity = {"activityType": {"typeKey": "lap_swimming"}}
        rows, _profile = fetch_one_activity_laps(activity, 2, **_laps_kwargs(rec))
        assert rec.typed_calls == [2]
        assert rec.splits_calls == []
        assert rows == [{"id": 2, "src": "typed"}]

    def test_open_water_swim_routes_to_raw_splits(self) -> None:
        rec = _Recorder()
        activity = {"activityType": {"typeKey": "open_water_swimming"}}
        _rows, _profile = fetch_one_activity_laps(activity, 3, **_laps_kwargs(rec))
        assert rec.splits_calls == [3]
        assert rec.typed_calls == []

    def test_returned_profile_matches_sport(self) -> None:
        rec = _Recorder()
        activity = {"activityType": {"typeKey": "cycling"}}
        _rows, profile = fetch_one_activity_laps(activity, 4, **_laps_kwargs(rec))
        assert "cycling" in profile.type_keys


# ---------------------------------------------------------------------------
# fetch_laps_for_activity -- multisport fan-out
# ---------------------------------------------------------------------------


class TestFetchLapsForActivity:
    def test_non_multisport_delegates_to_single(self) -> None:
        rec = _Recorder()
        activity = {"activityType": {"typeKey": "running"}}
        rows, _profile = fetch_laps_for_activity(
            activity,
            10,
            is_multisport_parent=lambda a: False,
            get_multisport_children=lambda a: [],
            **_laps_kwargs(rec),
        )
        assert rec.splits_calls == [10]
        # single (non-multisport) activities carry no leg_index
        assert all("leg_index" not in row for row in rows)

    def test_multisport_fans_out_and_stamps_leg_index(self) -> None:
        rec = _Recorder()
        parent = {"activityType": {"typeKey": "multi_sport"}}
        children = [
            {"activityId": 101, "activityType": {"typeKey": "open_water_swimming"}},
            {"activityId": 102, "activityType": {"typeKey": "cycling"}},
            {"activityId": 103, "activityType": {"typeKey": "running"}},
        ]
        rows, _profile = fetch_laps_for_activity(
            parent,
            100,
            is_multisport_parent=lambda a: True,
            get_multisport_children=lambda a: children,
            **_laps_kwargs(rec),
        )
        assert {row["leg_index"] for row in rows} == {0, 1, 2}
        # parent id never fetched; each child fetched once via raw splits
        assert rec.splits_calls == [101, 102, 103]
        assert rec.typed_calls == []

    def test_multisport_routes_lap_swim_child_to_typed(self) -> None:
        rec = _Recorder()
        parent = {"activityType": {"typeKey": "multi_sport"}}
        children = [
            {"activityId": 201, "activityType": {"typeKey": "lap_swimming"}},
            {"activityId": 202, "activityType": {"typeKey": "cycling"}},
        ]
        fetch_laps_for_activity(
            parent,
            200,
            is_multisport_parent=lambda a: True,
            get_multisport_children=lambda a: children,
            **_laps_kwargs(rec),
        )
        assert rec.typed_calls == [201]
        assert rec.splits_calls == [202]

    def test_multisport_skips_children_without_activity_id(self) -> None:
        rec = _Recorder()
        parent = {"activityType": {"typeKey": "multi_sport"}}
        children = [
            {"activityId": 301, "activityType": {"typeKey": "running"}},
            {"activityType": {"typeKey": "cycling"}},  # no activityId -> skipped
            {"activityId": 303, "activityType": {"typeKey": "running"}},
        ]
        rows, _profile = fetch_laps_for_activity(
            parent,
            300,
            is_multisport_parent=lambda a: True,
            get_multisport_children=lambda a: children,
            **_laps_kwargs(rec),
        )
        assert rec.splits_calls == [301, 303]
        assert {row["leg_index"] for row in rows} == {0, 2}

    def test_multisport_parent_without_children_falls_back_to_single(self) -> None:
        rec = _Recorder()
        parent = {"activityType": {"typeKey": "multi_sport"}}
        rows, _profile = fetch_laps_for_activity(
            parent,
            400,
            is_multisport_parent=lambda a: True,
            get_multisport_children=lambda a: [],
            **_laps_kwargs(rec),
        )
        # empty children -> treat parent itself as a single activity
        assert rec.splits_calls == [400]
        assert all("leg_index" not in row for row in rows)


# ---------------------------------------------------------------------------
# build_capability_manifest
# ---------------------------------------------------------------------------


def _serialize_detail(activity: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": activity.get("activityId")}]


def _serialize_manifest(
    activity: dict[str, Any],
    projected: dict[str, Any] | None = None,
    *,
    leg_index: int | None = None,
) -> list[dict[str, Any]]:
    return [{
        "field": "x",
        "activity_id": activity.get("activityId"),
        "projected": projected,
        "leg_index": leg_index,
    }]


class TestBuildCapabilityManifest:
    def test_single_activity_uses_parent_projection(self) -> None:
        activity = {"activityId": 1}
        rows = [{"id": 1, "value": 7}]
        manifest = build_capability_manifest(
            activity,
            rows,
            [],
            serialize_detail=_serialize_detail,
            serialize_manifest=_serialize_manifest,
        )
        assert manifest == [
            {"field": "x", "activity_id": 1, "projected": {"id": 1, "value": 7}, "leg_index": None}
        ]

    def test_single_activity_with_empty_rows_projects_none(self) -> None:
        manifest = build_capability_manifest(
            {"activityId": 5},
            [],
            [],
            serialize_detail=_serialize_detail,
            serialize_manifest=_serialize_manifest,
        )
        assert manifest[0]["projected"] is None

    def test_multisport_unions_children_with_leg_index(self) -> None:
        children = [
            {"activityId": 101},
            {"activityId": 102},
            {"activityId": 103},
        ]
        manifest = build_capability_manifest(
            {"activityId": 100},
            [{"id": 100}],
            children,
            serialize_detail=_serialize_detail,
            serialize_manifest=_serialize_manifest,
        )
        # one entry per child, leg_index 0..2, parent projection not used
        assert [e["leg_index"] for e in manifest] == [0, 1, 2]
        assert [e["activity_id"] for e in manifest] == [101, 102, 103]
        # each child entry is projected from that child's own detail row
        assert manifest[1]["projected"] == {"id": 102}
