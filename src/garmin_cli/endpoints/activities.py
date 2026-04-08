"""Activity endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

from datetime import date
from typing import Any

import garth

from garmin_cli.endpoints._base import _make_request, _validate_numeric_id
from garmin_cli.exceptions import GarminCliError


def _request(url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _make_request(garth.connectapi, url, params=params)


def list_activities(
    limit: int,
    start: int,
    activity_type: str | None,
    search: str | None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list:
    if limit <= 0:
        raise GarminCliError(
            error="limit must be greater than 0",
            error_code="INVALID_INPUT",
        )
    params: dict[str, Any] = {"start": start, "limit": limit}
    if activity_type is not None:
        params["activityType"] = activity_type
    if search is not None:
        params["search"] = search
    if start_date is not None:
        params["startDate"] = str(start_date)
    if end_date is not None:
        params["endDate"] = str(end_date)
    result = _request(
        "/activitylist-service/activities/search/activities",
        params=params,
    )
    if isinstance(result, dict):
        return [result]
    return result if result is not None else []


def get_activity(activity_id: Any) -> dict:
    validated = _validate_numeric_id(activity_id, "activity_id")
    result = _request(f"/activity-service/activity/{validated}")
    return result if result is not None else {}


def get_activity_splits(activity_id: Any) -> dict:
    validated = _validate_numeric_id(activity_id, "activity_id")
    result = _request(f"/activity-service/activity/{validated}/splits")
    return result if result is not None else {}


def get_multisport_children(parent: dict) -> list[dict]:
    """Fetch child activities for a multisport parent.

    Extracts child IDs from either ``childIds`` or
    ``metadataDTO.childIds`` and fetches each child activity.
    Returns an empty list if the activity is not a multisport parent.
    """
    child_ids: list[Any] = (
        parent.get("childIds")
        or (parent.get("metadataDTO") or {}).get("childIds")
        or []
    )
    if not child_ids:
        return []
    children: list[dict] = []
    for cid in child_ids:
        try:
            child = get_activity(cid)
            if child:
                children.append(child)
        except GarminCliError as exc:
            if exc.error_code == "NOT_FOUND":
                continue
            raise
    return children


def is_multisport_parent(activity: dict) -> bool:
    """Check whether an activity is a multisport parent."""
    if activity.get("isMultiSportParent") is True:
        return True
    metadata = activity.get("metadataDTO")
    if isinstance(metadata, dict):
        if metadata.get("isMultiSportParent") is True:
            return True
        if metadata.get("childIds"):
            return True
    if activity.get("childIds"):
        return True
    activity_type = activity.get("activityType")
    if isinstance(activity_type, dict):
        type_key = activity_type.get("typeKey", "")
        if type_key in ("multi_sport", "multisport"):
            return True
    return False


def get_activity_weather(activity_id: Any) -> dict:
    validated = _validate_numeric_id(activity_id, "activity_id")
    result = _request(f"/activity-service/activity/{validated}/weather")
    return result if result is not None else {}
