"""MCP resources for server discovery and cached athlete context."""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError

from garmin_cli import __version__, login_backoff
from garmin_cli.auth import _get_probe_ttl, _home_key, _probe_cache_hit, probe_session_status
from garmin_cli.config import CliConfig
from garmin_cli.date_utils import today
from garmin_cli.endpoints._base import _resolve_retry_delays, _validate_numeric_id
from garmin_cli.endpoints.activities import list_activities
from garmin_cli.endpoints.health import get_sleep
from garmin_cli.endpoints.performance import (
    get_all_thresholds,
    get_latest_vo2max,
)
from garmin_cli.endpoints.metrics import get_race_predictions
from garmin_cli.error_contracts import ERROR_CODE_TABLE
from garmin_cli.exceptions import TRANSIENT_ERROR_CODES, GarminCliError
from garmin_cli.mcp_tools._shared import _envelope, _error_text, mcp_recovery_hint
from garmin_cli.mcp_tools.activities import _AUTO_CELL_BUDGET, _activity_get_result
from garmin_cli.mcp_tools.coaching import TARGET_SAMPLE_BUDGET, TARGET_STREAM_LIMIT
from garmin_cli.token_store import token_file_identity
from garmin_cli.serializers import (
    serialize_activity_summary,
    serialize_race_predictions,
    serialize_sleep,
    serialize_thresholds,
    serialize_vo2max,
    select_latest_dated_rows,
)

_profile_cache_lock = threading.Lock()
# garmin_home -> (monotonic time, session identity, snapshot); a login or
# logout in any process changes the identity and invalidates the entry.
_profile_cache: dict[str, tuple[float, tuple[Any, ...], dict[str, Any]]] = {}


def _auth_state(config: CliConfig) -> tuple[str, dict[str, Any]]:
    # A recent successful probe (recorded by ensure_authenticated) makes a
    # fresh network round trip redundant for these read-only resources.
    if _probe_cache_hit(_home_key(config.garth_home), _get_probe_ttl()):
        return "authenticated", {
            "state": "authenticated",
            "latency_ms": 0.0,
            "error_code": None,
        }
    probe = probe_session_status(config)
    state = "authenticated" if probe.authenticated else "unauthenticated"
    auth: dict[str, Any] = {
        "state": state,
        "latency_ms": probe.latency_ms,
        "error_code": probe.error_code,
    }
    if probe.local_config:
        auth["local_config"] = True  # an unusable Garmin home: fix it locally, not by logging in
    return state, auth


def _tool_domain(name: str) -> str:
    return name.split("_", 1)[0]


async def _tool_inventory(mcp: MCPServer) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for tool in sorted(await mcp.list_tools(), key=lambda item: item.name):
        description = (tool.description or "").splitlines()[0]
        annotations = (
            tool.annotations.model_dump(exclude_none=True)
            if tool.annotations is not None
            else {}
        )
        grouped.setdefault(_tool_domain(tool.name), []).append({
            "name": tool.name,
            "description": description,
            "annotations": annotations,
        })
    return grouped


def _error_inventory() -> dict[str, dict[str, Any]]:
    retry_after = _resolve_retry_delays()[0]
    return {
        code: {
            **contract,
            "recovery_hint": mcp_recovery_hint(code),
            "retry_after_seconds": retry_after if code == "RATE_LIMITED" else None,
        }
        for code, contract in sorted(ERROR_CODE_TABLE.items())
    }


def _sum_numeric(rows: list[dict[str, Any]], key: str) -> float:
    return sum(
        value
        for row in rows
        if isinstance(value := row.get(key), (int, float))
        and not isinstance(value, bool)
    )


def _load_summary(
    activities: list[dict[str, Any]],
    as_of: date,
    days: int,
) -> dict[str, Any]:
    start = as_of - timedelta(days=days - 1)
    rows = [
        row
        for row in activities
        if isinstance(row.get("date"), str)
        and start.isoformat() <= row["date"][:10] <= as_of.isoformat()
    ]
    return {
        "days": days,
        "from": start.isoformat(),
        "to": as_of.isoformat(),
        "activity_count": len(rows),
        "duration_min": _sum_numeric(rows, "duration_min"),
        "distance_km": _sum_numeric(rows, "distance_km"),
        "training_load": _sum_numeric(rows, "training_load"),
    }


def _session_identity(garmin_home: str) -> tuple[Any, ...]:
    """This process's login count plus the token file's metadata (never its contents).

    A login or logout here bumps the generation; one in another process
    (``garmin-cli login`` / ``login logout``) rewrites or removes the file.
    """
    return (login_backoff.generation(garmin_home), token_file_identity(garmin_home))


def _latest_vo2max_per_sport(raw: Any) -> list[dict[str, Any]]:
    by_sport: dict[Any, list[dict[str, Any]]] = {}
    for row in serialize_vo2max(raw):
        if row.get("vo2max") is not None:
            by_sport.setdefault(row.get("sport"), []).append(row)
    return [row for rows in by_sport.values() for row in select_latest_dated_rows(rows)]


def _build_profile_snapshot(config: CliConfig) -> dict[str, Any]:
    # Cache first: a hit must cost zero network calls, including the auth probe.
    garmin_home = _home_key(config.garth_home)
    ttl = _get_probe_ttl()
    now = time.monotonic()
    with _profile_cache_lock:
        cached = _profile_cache.get(garmin_home)
        if (
            cached is not None
            and ttl > 0
            and now - cached[0] < ttl
            and cached[1] == _session_identity(garmin_home)
        ):
            return dict(cached[2])

    state, auth = _auth_state(config)
    if state != "authenticated":
        return {"auth_state": state, "auth": auth, "data": None}
    # The session the data is fetched under; a change during the fetches
    # (any process logging in or out) makes the snapshot uncacheable.
    identity = _session_identity(garmin_home)

    as_of = today()
    unavailable: list[dict[str, str]] = []
    # Only absent data (NOT_FOUND) is stable enough to cache; a throttle,
    # outage or unexpected error would otherwise be served for the whole TTL.
    cacheable = True

    def fetch(section: str, call: Any, serialize: Any) -> list[dict[str, Any]]:
        nonlocal cacheable
        try:
            return serialize(call())
        except Exception as exc:
            unavailable.append({"section": section, "reason": "unavailable"})
            if not (isinstance(exc, GarminCliError) and exc.error_code == "NOT_FOUND"):
                cacheable = False
            return []

    # Request budget: thresholds=3, VO2max=1, predictions=1, activities=1.
    thresholds = fetch("thresholds", get_all_thresholds, serialize_thresholds)
    vo2max = fetch("vo2max", get_latest_vo2max, _latest_vo2max_per_sport)
    race_predictions = fetch(
        "race_predictions",
        get_race_predictions,
        serialize_race_predictions,
    )
    activities = fetch(
        "activities",
        lambda: list_activities(
            100,
            0,
            None,
            None,
            as_of - timedelta(days=27),
            as_of,
        ),
        serialize_activity_summary,
    )
    result: dict[str, Any] = {
        "auth_state": state,
        "auth": auth,
        "data": {
            "as_of": as_of.isoformat(),
            "thresholds": thresholds,
            "vo2max": vo2max,
            "race_predictions": race_predictions,
            "load": {
                "last_7_days": _load_summary(activities, as_of, 7),
                "last_28_days": _load_summary(activities, as_of, 28),
            },
        },
        "request_budget": 6,
    }
    if unavailable:
        result["unavailable"] = unavailable
    if cacheable and _session_identity(garmin_home) == identity:
        with _profile_cache_lock:
            _profile_cache[garmin_home] = (now, identity, dict(result))
    return result


def _resource_validation_error(message: str) -> ResourceError:
    return ResourceError(_error_text(GarminCliError(error=message, error_code="INVALID_INPUT")))


def _parse_resource_activity_id(value: str) -> int:
    # The same strict rule as CLI ids: ASCII digits only, no sign, spaces or "_".
    try:
        return _validate_numeric_id(value, "activity_id")
    except GarminCliError as exc:
        raise _resource_validation_error(
            f"activity_id must be a positive integer, got '{value}'"
        ) from exc


def _parse_resource_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise _resource_validation_error(
            f"Invalid date format for date: expected YYYY-MM-DD, got '{value}'"
        ) from exc


def _require_resource_auth(config: CliConfig) -> None:
    state, auth = _auth_state(config)
    if state == "authenticated":
        return
    error_code = auth.get("error_code") or "AUTH_MISSING"
    local_config = bool(auth.get("local_config"))
    if local_config:
        message = "The Garmin session path is not usable"
    elif error_code == "AUTH_MISSING":
        message = "No usable saved session found"
    elif error_code in TRANSIENT_ERROR_CODES:
        message = "Could not check the Garmin session: Garmin throttled, failed, or was unreachable"
    else:
        message = "Garmin session is not authenticated"
    raise ResourceError(
        _error_text(GarminCliError(error=message, error_code=error_code, local_config=local_config))
    )


def _resource_payload(produce: Callable[[], Any]) -> str:
    """Serialize a resource read, mapping Garmin failures to ``ResourceError``."""
    try:
        return json.dumps(produce(), sort_keys=True)
    except GarminCliError as exc:
        raise ResourceError(_error_text(exc)) from exc


def register_resources(mcp: MCPServer, config: CliConfig) -> None:
    """Register discovery resources and the most-read entity templates."""

    @mcp.resource("garmin://server/manifest", mime_type="application/json")
    async def server_manifest() -> str:
        """Describe the Garmin MCP server's live capability surface."""
        state, auth = _auth_state(config)
        payload = {
            "server_version": __version__,
            "auth_state": state,
            "auth": auth,
            "tools": await _tool_inventory(mcp),
            "resources": {
                "static": [
                    "garmin://server/manifest",
                    "garmin://athlete/profile",
                ],
                "templates": [
                    {
                        "uri": "garmin://activity/{id}",
                        "description": "Serialized activity_get result by positive activity ID.",
                    },
                    {
                        "uri": "garmin://health/sleep/{date}",
                        "description": "Serialized health_sleep result for one ISO date.",
                    },
                ],
            },
            "error_codes": _error_inventory(),
            "envelope": {
                "read": {
                    "required": ["count", "rows"],
                    "count": "number of returned rows",
                    "rows": "serialized result rows",
                    "output_schema": (
                        "Row tools publish a plain object outputSchema; activity_get, activity_detail_metrics, "
                        "login_status, and submit_mfa_code publish typed outer fields."
                    ),
                },
                "write_validation": {
                    "required": ["count", "rows"],
                    "row": {
                        "ok": False,
                        "error_code": "INVALID_INPUT",
                        "errors": ["validation issue"],
                    },
                },
            },
            "limits": {
                "date_range_days": 90,
                "activity_list_limit": 100,
                "activity_laps_rows": 100,
                "activity_detail_metrics_auto_cell_budget": _AUTO_CELL_BUDGET,
                "activity_detail_metrics_max_samples": 5000,
                "reconciliation_range_days": 28,
                "reconciliation_max_activities": 100,
                "reconciliation_target_streams_per_call": TARGET_STREAM_LIMIT,
                "reconciliation_target_samples_per_stream": TARGET_SAMPLE_BUDGET,
            },
        }
        return json.dumps(payload, sort_keys=True)

    @mcp.resource("garmin://athlete/profile", mime_type="application/json")
    def athlete_profile() -> str:
        """Return a cheap cached athlete thresholds, predictions, and load snapshot."""
        return json.dumps(_build_profile_snapshot(config), sort_keys=True)

    @mcp.resource(
        "garmin://activity/{id}",
        mime_type="application/json",
        description="Serialized activity_get result for one activity ID.",
    )
    def activity_resource(id: str) -> str:
        """Return the same envelope as ``activity_get(detail=False)``."""
        activity_id = _parse_resource_activity_id(id)
        _require_resource_auth(config)
        return _resource_payload(lambda: _activity_get_result(activity_id))

    @mcp.resource(
        "garmin://health/sleep/{date}",
        mime_type="application/json",
        description="Serialized health_sleep result for one ISO date.",
    )
    def sleep_resource(date: str) -> str:
        """Return the same envelope as a one-day ``health_sleep`` read."""
        parsed_date = _parse_resource_date(date)
        _require_resource_auth(config)
        return _resource_payload(
            lambda: _envelope(serialize_sleep(get_sleep(parsed_date, parsed_date)))
        )
