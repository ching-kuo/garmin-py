"""MCP resources for server discovery and cached athlete context."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer

from garmin_cli import __version__
from garmin_cli.auth import _get_probe_ttl, _probe_cache_hit, probe_session_status
from garmin_cli.config import CliConfig
from garmin_cli.endpoints._base import _resolve_retry_delays
from garmin_cli.endpoints.activities import list_activities
from garmin_cli.endpoints.performance import (
    get_all_thresholds,
    get_latest_vo2max,
)
from garmin_cli.endpoints.metrics import get_race_predictions
from garmin_cli.error_contracts import ERROR_CODE_TABLE
from garmin_cli.mcp_tools.coaching import TARGET_SAMPLE_BUDGET, TARGET_STREAM_LIMIT
from garmin_cli.serializers import (
    serialize_activity_summary,
    serialize_race_predictions,
    serialize_thresholds,
    serialize_vo2max,
)

_profile_cache_lock = threading.Lock()
_profile_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _auth_state(config: CliConfig) -> tuple[str, dict[str, Any]]:
    # A recent successful probe (recorded by ensure_authenticated) makes a
    # fresh network round trip redundant for these read-only resources.
    if _probe_cache_hit(os.path.expanduser(config.garth_home), _get_probe_ttl()):
        return "authenticated", {
            "state": "authenticated",
            "latency_ms": 0.0,
            "error_code": None,
        }
    probe = probe_session_status(config)
    state = "authenticated" if probe.authenticated else "unauthenticated"
    return state, {
        "state": state,
        "latency_ms": probe.latency_ms,
        "error_code": probe.error_code,
    }


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


def _build_profile_snapshot(config: CliConfig) -> dict[str, Any]:
    # Cache first: a hit must cost zero network calls, including the auth probe.
    garmin_home = os.path.expanduser(config.garth_home)
    ttl = _get_probe_ttl()
    now = time.monotonic()
    with _profile_cache_lock:
        cached = _profile_cache.get(garmin_home)
        if cached is not None and ttl > 0 and now - cached[0] < ttl:
            return dict(cached[1])

    state, auth = _auth_state(config)
    if state != "authenticated":
        return {"auth_state": state, "auth": auth, "data": None}

    as_of = date.today()
    unavailable: list[dict[str, str]] = []

    def fetch(section: str, call: Any, serialize: Any) -> list[dict[str, Any]]:
        try:
            return serialize(call())
        except Exception:
            unavailable.append({"section": section, "reason": "unavailable"})
            return []

    # Request budget: thresholds=3, VO2max=1, predictions=1, activities=1.
    thresholds = fetch("thresholds", get_all_thresholds, serialize_thresholds)
    vo2max = fetch("vo2max", get_latest_vo2max, serialize_vo2max)
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
    with _profile_cache_lock:
        _profile_cache[garmin_home] = (now, dict(result))
    return result


def register_resources(mcp: MCPServer, config: CliConfig) -> None:
    """Register server manifest and athlete profile resources."""

    @mcp.resource("garmin://server/manifest", mime_type="application/json")
    async def server_manifest() -> str:
        """Describe the Garmin MCP server's live capability surface."""
        state, auth = _auth_state(config)
        payload = {
            "server_version": __version__,
            "auth_state": state,
            "auth": auth,
            "tools": await _tool_inventory(mcp),
            "error_codes": _error_inventory(),
            "envelope": {
                "read": {
                    "required": ["count", "rows"],
                    "count": "number of returned rows",
                    "rows": "serialized result rows",
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
                "steps_window_days": 28,
                "activity_laps_rows": 100,
                "activity_detail_metrics_default_samples": 1000,
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
