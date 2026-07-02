"""Activity endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

from concurrent.futures import Future
from datetime import date
from pathlib import Path
from typing import Any

from garminconnect import Garmin

from garmin_cli import backend as garth
from garmin_cli.endpoints._base import (
    _bounded_thread_pool,
    _cancel_futures_on_error,
    _make_request,
    _make_typed_request,
    _make_typed_write,
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
    # External callers (CLI ``validate_limit`` / MCP ``_validate_limit``)
    # enforce the positive-limit contract; internal callers (report_snapshot
    # in mcp_tools/misc.py) pass hardcoded positive literals. No re-check here.
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
    ``metadataDTO.childIds`` and fetches each child activity concurrently
    on a bounded thread pool; the returned list preserves child-ID order.
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
    futures: list[Future[Any]] = []
    with _bounded_thread_pool(len(child_ids)) as pool, _cancel_futures_on_error(futures):
        for cid in child_ids:
            futures.append(pool.submit(get_activity, cid))
        for future in futures:
            try:
                child = future.result()
            except GarminCliError as exc:
                if exc.error_code == "NOT_FOUND":
                    continue
                raise
            if child:
                children.append(child)
    return children


def activity_type_key(activity: Any) -> str | None:
    """Return the sport ``typeKey`` from an activity payload, or None.

    Garmin nulls the top-level ``activityType`` on some detail payloads and
    carries the real sport under ``activityTypeDTO``; both are checked so
    sport routing (lap columns, capability flags) never silently defaults.
    """
    if not isinstance(activity, dict):
        return None
    for container_key in ("activityType", "activityTypeDTO"):
        container = activity.get(container_key)
        if isinstance(container, dict):
            type_key = container.get("typeKey")
            if type_key is not None:
                return type_key
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
    # Use the shared resolver so a null top-level activityType (sport carried
    # under activityTypeDTO) still classifies a multisport parent correctly.
    if activity_type_key(activity) in ("multi_sport", "multisport"):
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
    result = _make_typed_write(garth.download_activity, validated, dl_fmt)
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
    return _make_typed_write(garth.upload_activity, str(p))


def delete_activity(activity_id: Any) -> None:
    """Delete an activity by ID."""
    validated = _validate_numeric_id(activity_id, "activity_id")
    _make_typed_write(
        garth.delete_activity,
        validated,
    )


def get_activity_types() -> list[dict]:
    """Return the Garmin sport-type table (typeKey/typeId/parentTypeId rows)."""
    result = _make_typed_request(garth.get_activity_types)
    return result if isinstance(result, list) else []


def _resolve_activity_type(type_key: str) -> tuple[int, int]:
    """Resolve a sport ``typeKey`` to its ``(typeId, parentTypeId)`` pair.

    The pair is looked up from the live Garmin type table rather than a
    hardcoded list, so the accepted keys always track the account's server.
    Raises ``INVALID_INPUT`` for a blank or unknown key.
    """
    normalized = type_key.strip().lower()
    if not normalized:
        raise GarminCliError(
            error="Activity type key must be non-empty.",
            error_code="INVALID_INPUT",
        )
    key_found_malformed = False
    for entry in get_activity_types():
        if not isinstance(entry, dict) or entry.get("typeKey") != normalized:
            continue
        type_id = entry.get("typeId")
        parent_type_id = entry.get("parentTypeId")
        if (
            isinstance(type_id, int)
            and not isinstance(type_id, bool)
            and isinstance(parent_type_id, int)
            and not isinstance(parent_type_id, bool)
        ):
            return type_id, parent_type_id
        key_found_malformed = True
    if key_found_malformed:
        raise GarminCliError(
            error=(
                f"Activity type '{type_key}' exists but has malformed id fields "
                "in Garmin's type table."
            ),
            error_code="SERVER_ERROR",
        )
    raise GarminCliError(
        error=f"Unknown activity type key: '{type_key}'.",
        error_code="INVALID_INPUT",
    )


def set_activity_name(activity_id: Any, name: str) -> Any:
    """Rename an activity. The name must be non-empty."""
    validated = _validate_numeric_id(activity_id, "activity_id")
    if not name or not name.strip():
        raise GarminCliError(
            error="Activity name must be non-empty.",
            error_code="INVALID_INPUT",
        )
    return _make_typed_write(garth.set_activity_name, validated, name)


def set_activity_type(activity_id: Any, type_key: str) -> Any:
    """Set an activity's sport type from a ``typeKey`` (e.g. ``running``).

    Resolves the key to Garmin's ``typeId``/``parentTypeId`` via the live
    type table before issuing the update.
    """
    validated = _validate_numeric_id(activity_id, "activity_id")
    type_id, parent_type_id = _resolve_activity_type(type_key)
    return _make_typed_write(
        garth.set_activity_type,
        validated,
        type_id,
        type_key.strip().lower(),
        parent_type_id,
    )
