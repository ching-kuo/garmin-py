"""Activity endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from garminconnect import Garmin

from garmin_cli import backend as garth
from garmin_cli.endpoints._base import (
    _make_request,
    _make_typed_request,
    _validate_numeric_id,
)
from garmin_cli.exceptions import GarminCliError

# Canonical format strings → ActivityDownloadFormat enum members
_DOWNLOAD_FORMAT_MAP: dict[str, Any] = {
    "original": Garmin.ActivityDownloadFormat.ORIGINAL,
    "tcx": Garmin.ActivityDownloadFormat.TCX,
    "gpx": Garmin.ActivityDownloadFormat.GPX,
    "kml": Garmin.ActivityDownloadFormat.KML,
    "csv": Garmin.ActivityDownloadFormat.CSV,
}

# File extension for each download format (used for default output filename)
_DOWNLOAD_EXTENSIONS: dict[str, str] = {
    "original": ".zip",
    "tcx": ".tcx",
    "gpx": ".gpx",
    "kml": ".kml",
    "csv": ".csv",
}

# Valid upload extensions (must match Garmin.ActivityUploadFormat members)
_UPLOAD_EXTENSIONS: frozenset[str] = frozenset({"fit", "gpx", "tcx"})


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


def get_activity_typed_splits(activity_id: Any) -> dict:
    """Wrap the backend's typed get_activity_typed_splits helper.

    Calls the python-garminconnect typed method rather than a raw URL string,
    eliminating URL-casing risk. Used for per-pool-length swim data.
    """
    validated = _validate_numeric_id(activity_id, "activity_id")
    result = _make_typed_request(garth.get_activity_typed_splits, validated)
    return result if result is not None else {}


def get_activity_hr_in_timezones(activity_id: Any) -> list:
    """Wrap the backend's typed get_activity_hr_in_timezones helper.

    Returns the per-zone time-in-zone breakdown for an activity. Calls the
    python-garminconnect typed method rather than a raw URL string. Some
    upstream releases wrap the array under a ``timeInZones`` (or related)
    key — unwrap defensively so downstream serializers see a flat list.
    """
    validated = _validate_numeric_id(activity_id, "activity_id")
    result = _make_typed_request(garth.get_activity_hr_in_timezones, validated)
    if result is None:
        return []
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("timeInZones", "timeInZone", "hrTimeInZones", "zones"):
            container = result.get(key)
            if isinstance(container, list):
                return container
    return []


def get_activity_details(activity_id: Any) -> dict:
    """Wrap the backend's typed get_activity_details helper.

    Returns the metric-descriptor + sample-stream payload. Used by
    ``activity_metrics_describe`` to expose the dynamic schema.
    """
    validated = _validate_numeric_id(activity_id, "activity_id")
    result = _make_typed_request(garth.get_activity_details, validated)
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


def activity_type_key(activity: Any) -> str | None:
    """Return ``activityType.typeKey`` from an activity payload, or None."""
    if isinstance(activity, dict):
        activity_type = activity.get("activityType")
        if isinstance(activity_type, dict):
            return activity_type.get("typeKey")
    return None


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


def download_activity(activity_id: Any, fmt: str = "original") -> bytes:
    """Download an activity in the requested format and return raw bytes.

    *fmt* must be one of: original, tcx, gpx, kml, csv.
    For ``original``, Garmin returns a ZIP archive containing the FIT file.
    """
    validated = _validate_numeric_id(activity_id, "activity_id")
    fmt_lower = fmt.lower()
    if fmt_lower not in _DOWNLOAD_FORMAT_MAP:
        allowed = ", ".join(sorted(_DOWNLOAD_FORMAT_MAP))
        raise GarminCliError(
            error=f"Invalid download format '{fmt}'. Allowed values: {allowed}.",
            error_code="INVALID_INPUT",
        )
    dl_fmt = _DOWNLOAD_FORMAT_MAP[fmt_lower]
    result = _make_typed_request(garth.download_activity, validated, dl_fmt)
    if not isinstance(result, (bytes, bytearray)):
        raise GarminCliError(
            error="Download returned unexpected non-bytes response.",
            error_code="SERVER_ERROR",
        )
    return bytes(result)


def extension_for_format(fmt: str) -> str:
    """Return the file extension (with leading dot) for a download format string."""
    return _DOWNLOAD_EXTENSIONS.get(fmt.lower(), f".{fmt.lower()}")


def upload_activity(file_path: str) -> Any:
    """Upload an activity file (FIT, GPX, or TCX) to Garmin Connect.

    The file must exist on disk and have a supported extension.
    """
    p = Path(file_path)
    if not p.exists():
        raise GarminCliError(
            error=f"File not found: {file_path}",
            error_code="INVALID_INPUT",
        )
    if not p.is_file():
        raise GarminCliError(
            error=f"Path is not a file: {file_path}",
            error_code="INVALID_INPUT",
        )
    ext = p.suffix.lstrip(".").lower()
    if ext not in _UPLOAD_EXTENSIONS:
        allowed = ", ".join(f".{e}" for e in sorted(_UPLOAD_EXTENSIONS))
        raise GarminCliError(
            error=f"Unsupported file extension '.{ext}'. Allowed: {allowed}.",
            error_code="INVALID_INPUT",
        )
    return _make_typed_request(garth.upload_activity, str(p))


def delete_activity(activity_id: Any) -> None:
    """Delete an activity by ID."""
    validated = _validate_numeric_id(activity_id, "activity_id")
    _make_typed_request(
        garth.delete_activity,
        validated,
    )
