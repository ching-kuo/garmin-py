"""MCP resource discovery and payload contract tests."""
from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli import auth as auth_module  # noqa: E402
from garmin_cli.auth import SessionProbeResult  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from garmin_cli.mcp_tools import resources as resources_module  # noqa: E402
from tests.test_mcp_tools.support import _config  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the profile cache and shared auth-probe cache between tests."""
    monkeypatch.setattr(resources_module, "_profile_cache", {})
    auth_module._invalidate_probe_cache()


def _read(server: Any, uri: str) -> dict[str, Any]:
    contents = asyncio.run(server.read_resource(uri))
    return json.loads(contents[0].content)


def _unauthenticated_probe() -> SessionProbeResult:
    return SessionProbeResult(
        authenticated=False,
        garmin_home="/tmp/garth",
        latency_ms=1.0,
        error_code="AUTH_MISSING",
        detail="missing",
    )


def test_server_lists_exactly_two_resources() -> None:
    server = create_mcp_server(_config())

    resources = asyncio.run(server.list_resources())

    assert {str(resource.uri) for resource in resources} == {
        "garmin://server/manifest",
        "garmin://athlete/profile",
    }
    templates = asyncio.run(server.list_resource_templates())
    assert {str(template.uri_template) for template in templates} == {
        "garmin://activity/{id}",
        "garmin://health/sleep/{date}",
    }


def test_activity_template_matches_activity_get_envelope(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.mcp_tools.resources._auth_state",
        return_value=("authenticated", {"state": "authenticated"}),
    )
    mocker.patch(
        "garmin_cli.mcp_tools.activities.get_activity",
        return_value={
            "activityId": 123,
            "startTimeLocal": "2026-01-01",
            "activityName": "Run",
            "activityType": {"typeKey": "running"},
            "distance": 10000,
            "duration": 3600,
        },
    )
    server = create_mcp_server(_config())

    payload = _read(server, "garmin://activity/123")

    assert payload["count"] == 1
    assert payload["rows"][0]["id"] == 123


def test_sleep_template_matches_one_day_health_sleep_envelope(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.mcp_tools.resources._auth_state",
        return_value=("authenticated", {"state": "authenticated"}),
    )
    get_sleep = mocker.patch(
        "garmin_cli.mcp_tools.resources.get_sleep",
        return_value=[{"dailySleepDTO": {"calendarDate": "2026-01-01", "sleepTimeSeconds": 28800}}],
    )
    server = create_mcp_server(_config())

    payload = _read(server, "garmin://health/sleep/2026-01-01")

    assert payload["count"] == 1
    assert payload["rows"][0]["date"] == "2026-01-01"
    get_sleep.assert_called_once_with(date(2026, 1, 1), date(2026, 1, 1))


@pytest.mark.parametrize(
    ("uri", "error_code"),
    [
        ("garmin://activity/not-an-id", "INVALID_INPUT"),
        ("garmin://health/sleep/not-a-date", "INVALID_INPUT"),
    ],
)
def test_template_validation_errors_keep_json_error_contract(
    uri: str,
    error_code: str,
) -> None:
    server = create_mcp_server(_config())

    with pytest.raises(Exception) as exc_info:
        asyncio.run(server.read_resource(uri))

    payload = json.loads(str(exc_info.value))
    assert payload["error_code"] == error_code


def test_template_auth_error_keeps_json_error_contract(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.mcp_tools.resources._auth_state",
        return_value=("unauthenticated", {"error_code": "AUTH_MISSING"}),
    )
    server = create_mcp_server(_config())

    with pytest.raises(Exception) as exc_info:
        asyncio.run(server.read_resource("garmin://activity/123"))

    payload = json.loads(str(exc_info.value))
    assert payload["error_code"] == "AUTH_MISSING"


def test_manifest_inventory_matches_registered_tools(
    mocker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GARMIN_CLI_RETRY_DELAYS", raising=False)
    mocker.patch(
        "garmin_cli.mcp_tools.resources.probe_session_status",
        return_value=_unauthenticated_probe(),
    )
    server = create_mcp_server(_config())

    manifest = _read(server, "garmin://server/manifest")
    registered = {tool.name for tool in asyncio.run(server.list_tools())}
    inventoried = {
        tool["name"]
        for tools in manifest["tools"].values()
        for tool in tools
    }

    assert inventoried == registered
    assert manifest["limits"]["activity_laps_rows"] == 100
    assert manifest["limits"]["activity_detail_metrics_default_samples"] == 1000
    assert manifest["limits"]["reconciliation_target_streams_per_call"] == 10
    assert manifest["error_codes"]["RATE_LIMITED"]["retry_after_seconds"] == 2
    assert {
        resource["uri"] for resource in manifest["resources"]["templates"]
    } == {
        "garmin://activity/{id}",
        "garmin://health/sleep/{date}",
    }


def test_unauthenticated_profile_returns_structured_body_without_fetches(
    mocker: Any,
) -> None:
    mocker.patch(
        "garmin_cli.mcp_tools.resources.probe_session_status",
        return_value=_unauthenticated_probe(),
    )
    threshold = mocker.patch("garmin_cli.mcp_tools.resources.get_all_thresholds")
    activities = mocker.patch("garmin_cli.mcp_tools.resources.list_activities")
    server = create_mcp_server(_config())

    profile = _read(server, "garmin://athlete/profile")

    assert profile == {
        "auth": {
            "error_code": "AUTH_MISSING",
            "latency_ms": 1.0,
            "state": "unauthenticated",
        },
        "auth_state": "unauthenticated",
        "data": None,
    }
    threshold.assert_not_called()
    activities.assert_not_called()


def test_profile_snapshot_stays_within_six_request_budget(
    mocker: Any,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "0")
    mocker.patch(
        "garmin_cli.mcp_tools.resources.probe_session_status",
        return_value=SessionProbeResult(
            authenticated=True,
            garmin_home="/tmp/garth",
            latency_ms=1.0,
            detail="valid",
        ),
    )
    # get_all_thresholds owns three upstream calls; the other three patched
    # functions each own one.
    mocker.patch(
        "garmin_cli.mcp_tools.resources.get_all_thresholds",
        return_value={"thresholds": []},
    )
    mocker.patch(
        "garmin_cli.mcp_tools.resources.get_latest_vo2max",
        return_value=[],
    )
    mocker.patch(
        "garmin_cli.mcp_tools.resources.get_race_predictions",
        return_value={},
    )
    mocker.patch(
        "garmin_cli.mcp_tools.resources.list_activities",
        return_value=[
            {
                "activityId": 1,
                "startTimeLocal": date.today().isoformat() + "T08:00:00",
                "activityType": {"typeKey": "running"},
                "duration": 3600,
                "distance": 10000,
                "activityTrainingLoad": 50,
            },
        ],
    )
    server = create_mcp_server(_config())

    profile = _read(server, "garmin://athlete/profile")

    assert profile["auth_state"] == "authenticated"
    assert profile["request_budget"] == 6
    assert profile["data"]["load"]["last_7_days"]["activity_count"] == 1


def test_profile_cache_hit_makes_no_upstream_calls(
    mocker: Any,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
    probe = mocker.patch(
        "garmin_cli.mcp_tools.resources.probe_session_status",
        return_value=SessionProbeResult(
            authenticated=True,
            garmin_home="/tmp/garth",
            latency_ms=1.0,
            detail="valid",
        ),
    )
    thresholds = mocker.patch(
        "garmin_cli.mcp_tools.resources.get_all_thresholds",
        return_value={"thresholds": []},
    )
    mocker.patch("garmin_cli.mcp_tools.resources.get_latest_vo2max", return_value=[])
    mocker.patch("garmin_cli.mcp_tools.resources.get_race_predictions", return_value={})
    mocker.patch("garmin_cli.mcp_tools.resources.list_activities", return_value=[])
    server = create_mcp_server(_config())

    first = _read(server, "garmin://athlete/profile")
    second = _read(server, "garmin://athlete/profile")

    assert first == second
    assert probe.call_count == 1
    assert thresholds.call_count == 1
