"""MCP resource discovery and payload contract tests."""
from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli import auth as auth_module  # noqa: E402
from garmin_cli import login_backoff  # noqa: E402
from garmin_cli.auth import SessionProbeResult  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from garmin_cli.mcp_tools import resources as resources_module  # noqa: E402
from tests.test_mcp_tools.support import _config  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the profile cache and shared auth-probe cache between tests."""
    monkeypatch.setattr(resources_module, "_profile_cache", {})
    monkeypatch.setattr(login_backoff, "_generations", {})
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


def test_sleep_template_cold_start_uses_probe_resumed_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Resources authenticate only via the read-only probe; its client must serve the read."""
    from garmin_cli import backend

    home = tmp_path / "garth"
    home.mkdir(mode=0o700)
    (home / "garmin_tokens.json").write_text("{}")
    sleep = [{"dailySleepDTO": {"calendarDate": "2026-01-01", "sleepTimeSeconds": 28800}}]

    class _FakeGarmin:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def login(self, tokenstore: str | None = None) -> tuple[None, None]:
            return None, None

        def connectapi(self, path: str, **_kwargs: Any) -> Any:
            return sleep if "dailySleeps" in path else {}

    monkeypatch.setattr(backend, "Garmin", _FakeGarmin)
    monkeypatch.setattr(backend, "_apply_timeout", lambda _client: None)
    monkeypatch.setattr(backend, "_serialize_refresh", lambda _client: None)
    monkeypatch.setattr(backend, "_surface_refresh_failures", lambda _client: None)
    monkeypatch.setattr(backend, "_backend", None)
    monkeypatch.setattr(backend, "_garth_home", None)
    monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "0")
    server = create_mcp_server(_config(garth_home=str(home)))

    payload = _read(server, "garmin://health/sleep/2026-01-01")

    assert payload["count"] == 1
    assert payload["rows"][0]["date"] == "2026-01-01"


@pytest.mark.parametrize(
    ("uri", "error_code"),
    [
        ("garmin://activity/not-an-id", "INVALID_INPUT"),
        ("garmin://activity/+12", "INVALID_INPUT"),
        ("garmin://activity/1_2", "INVALID_INPUT"),
        ("garmin://activity/0", "INVALID_INPUT"),
        ("garmin://activity/" + "9" * 21, "INVALID_INPUT"),
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


def test_template_probe_outage_is_not_reported_as_unauthenticated(mocker: Any) -> None:
    mocker.patch(
        "garmin_cli.mcp_tools.resources._auth_state",
        return_value=("unauthenticated", {"error_code": "NETWORK_ERROR"}),
    )
    server = create_mcp_server(_config())

    with pytest.raises(Exception) as exc_info:
        asyncio.run(server.read_resource("garmin://activity/123"))

    payload = json.loads(str(exc_info.value))
    assert payload["error_code"] == "NETWORK_ERROR"
    assert "not authenticated" not in payload["message"]


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
    assert manifest["limits"]["activity_detail_metrics_auto_cell_budget"] == 2400
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


def _authenticated_profile_mocks(mocker: Any, monkeypatch: Any) -> Any:
    monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
    mocker.patch(
        "garmin_cli.mcp_tools.resources._auth_state",
        return_value=("authenticated", {"state": "authenticated"}),
    )
    mocker.patch("garmin_cli.mcp_tools.resources.get_latest_vo2max", return_value=[])
    mocker.patch("garmin_cli.mcp_tools.resources.get_race_predictions", return_value={})
    mocker.patch("garmin_cli.mcp_tools.resources.list_activities", return_value=[])
    return mocker.patch(
        "garmin_cli.mcp_tools.resources.get_all_thresholds",
        return_value={"thresholds": []},
    )


def test_profile_vo2max_keeps_the_latest_row_per_sport(mocker: Any, monkeypatch: Any) -> None:
    _authenticated_profile_mocks(mocker, monkeypatch)
    mocker.patch(
        "garmin_cli.mcp_tools.resources.get_latest_vo2max",
        return_value=[
            {"calendarDate": "2026-01-01", "vo2MaxValue": 50, "sport": "running"},
            {"calendarDate": "2026-01-03", "vo2MaxValue": 58, "sport": "cycling"},
            {"calendarDate": "2026-01-05", "vo2MaxValue": 52, "sport": "running"},
            # A newer day without a value must not hide the latest real one.
            {"calendarDate": "2026-01-07", "vo2MaxValue": None, "sport": "cycling"},
        ],
    )

    profile = _read(create_mcp_server(_config()), "garmin://athlete/profile")

    assert sorted(profile["data"]["vo2max"], key=lambda row: row["sport"]) == [
        {"date": "2026-01-03", "vo2max": 58, "sport": "cycling"},
        {"date": "2026-01-05", "vo2max": 52, "sport": "running"},
    ]


@pytest.mark.parametrize(
    ("errors", "cached"),
    [
        (["RATE_LIMITED"], False),
        (["SERVER_ERROR"], False),
        (["NETWORK_ERROR"], False),
        (["NOT_FOUND"], True),
        (["NOT_FOUND", "RATE_LIMITED"], False),
        ([None], False),  # a non-Garmin exception
    ],
)
def test_profile_caches_only_when_every_failure_is_not_found(
    mocker: Any, monkeypatch: Any, errors: list[str | None], cached: bool
) -> None:
    from garmin_cli.exceptions import GarminCliError

    def failure(code: str | None) -> Exception:
        return RuntimeError("boom") if code is None else GarminCliError(error="boom", error_code=code)

    thresholds = _authenticated_profile_mocks(mocker, monkeypatch)
    thresholds.side_effect = failure(errors[0])
    if len(errors) > 1:
        mocker.patch("garmin_cli.mcp_tools.resources.get_race_predictions", side_effect=failure(errors[1]))
    server = create_mcp_server(_config())

    first = _read(server, "garmin://athlete/profile")
    _read(server, "garmin://athlete/profile")

    assert first["unavailable"][0] == {"section": "thresholds", "reason": "unavailable"}
    assert thresholds.call_count == (1 if cached else 2)


def test_profile_cache_is_dropped_when_the_token_file_changes(
    mocker: Any, monkeypatch: Any, tmp_path: Any
) -> None:
    # A login or logout in another process rewrites or removes the token file.
    thresholds = _authenticated_profile_mocks(mocker, monkeypatch)
    token_file = tmp_path / "garmin_tokens.json"
    token_file.write_text("{}")
    server = create_mcp_server(_config(garth_home=str(tmp_path)))

    _read(server, "garmin://athlete/profile")
    _read(server, "garmin://athlete/profile")
    token_file.write_text('{"rotated": true}')
    _read(server, "garmin://athlete/profile")
    token_file.unlink()
    _read(server, "garmin://athlete/profile")

    assert thresholds.call_count == 3


@pytest.mark.parametrize("change", ["logout", "account_switch"])
def test_cross_process_session_change_refreshes_auth_and_profile(
    mocker: Any, monkeypatch: Any, tmp_path: Any, change: str
) -> None:
    # The real auth-state path: a warm probe cache, then another process
    # logs out (token file removed) or logs in as someone else (rewritten).
    monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
    token_file = tmp_path / "garmin_tokens.json"
    token_file.write_text("{}")
    auth_module._record_probe_ok(auth_module._home_key(str(tmp_path)))
    probe = mocker.patch(
        "garmin_cli.mcp_tools.resources.probe_session_status",
        return_value=SessionProbeResult(
            authenticated=change == "account_switch", garmin_home=str(tmp_path), latency_ms=1.0, detail=""
        ),
    )
    thresholds = mocker.patch(
        "garmin_cli.mcp_tools.resources.get_all_thresholds", return_value={"thresholds": []}
    )
    mocker.patch("garmin_cli.mcp_tools.resources.get_latest_vo2max", return_value=[])
    mocker.patch("garmin_cli.mcp_tools.resources.get_race_predictions", return_value={})
    mocker.patch("garmin_cli.mcp_tools.resources.list_activities", return_value=[])
    server = create_mcp_server(_config(garth_home=str(tmp_path)))

    assert _read(server, "garmin://athlete/profile")["auth_state"] == "authenticated"
    probe.assert_not_called()  # the warm probe cache answered
    if change == "logout":
        token_file.unlink()
    else:
        token_file.write_text('{"account": "other"}')
    second = _read(server, "garmin://athlete/profile")

    probe.assert_called_once()
    if change == "logout":
        assert second["auth_state"] == "unauthenticated"
        assert thresholds.call_count == 1
    else:
        assert second["auth_state"] == "authenticated"
        assert thresholds.call_count == 2


def test_profile_snapshot_is_not_cached_when_the_session_changes_mid_fetch(
    mocker: Any, monkeypatch: Any, tmp_path: Any
) -> None:
    thresholds = _authenticated_profile_mocks(mocker, monkeypatch)
    token_file = tmp_path / "garmin_tokens.json"
    token_file.write_text("{}")
    mocker.patch(
        "garmin_cli.mcp_tools.resources.get_race_predictions",
        side_effect=lambda: token_file.write_text('{"rotated": true}') and {},
    )
    server = create_mcp_server(_config(garth_home=str(tmp_path)))

    _read(server, "garmin://athlete/profile")
    _read(server, "garmin://athlete/profile")

    assert thresholds.call_count == 2


def test_profile_cache_is_dropped_after_a_new_login(mocker: Any, monkeypatch: Any) -> None:
    thresholds = _authenticated_profile_mocks(mocker, monkeypatch)
    config = _config()
    server = create_mcp_server(config)

    _read(server, "garmin://athlete/profile")
    login_backoff.record_success(auth_module._home_key(config.garth_home))
    _read(server, "garmin://athlete/profile")

    assert thresholds.call_count == 2
