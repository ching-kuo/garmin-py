"""Offline CLI and MCP contracts backed by sanitized backend fixtures."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.cli import cli  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.backend_fixtures import BackendFixtureController  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


@pytest.fixture()
def replay_backend(monkeypatch: pytest.MonkeyPatch) -> Path:
    root = Path(__file__).parents[1] / "fixtures" / "backend"
    BackendFixtureController("replay", root).install(monkeypatch)
    monkeypatch.setattr(
        "garmin_cli.commands._options.ensure_authenticated",
        lambda _config: None,
    )
    monkeypatch.setattr(
        "garmin_cli.mcp_tools._shared.ensure_authenticated",
        lambda _config: None,
    )
    return root


def test_cli_sleep_contract_replays_without_tokens_or_network(
    replay_backend: Path,
) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "--json",
            "--garmin-home",
            str(replay_backend / "no-token-store"),
            "health",
            "sleep",
            "--from",
            "2026-07-01",
            "--to",
            "2026-07-01",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {"ok", "command", "count", "data", "date_range"}
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["date_range"] == {
        "from": "2026-07-01",
        "to": "2026-07-01",
    }
    row = payload["data"][0]
    assert isinstance(row["date"], str)
    assert isinstance(row["score"], int)
    assert isinstance(row["duration_hours"], float)


def test_mcp_activity_contracts_replay_list_detail_and_laps(
    replay_backend: Path,
) -> None:
    server = create_mcp_server(_config(garth_home=str(replay_backend)))

    listing = _call(
        server,
        "activity_list",
        {
            "limit": 20,
            "start_date": "2026-07-01",
            "end_date": "2026-07-14",
        },
    )
    detail = _call(server, "activity_get", {"activity_id": 2001, "detail": True})
    laps = _call(server, "activity_laps", {"activity_id": 2001})

    assert set(listing) == {"count", "rows"}
    assert listing["count"] == 2
    assert {"id", "date", "type", "distance_km", "duration_min"} <= set(
        listing["rows"][0]
    )
    assert detail["count"] == 1
    assert detail["rows"][0]["id"] == 2001
    assert detail["rows"][0]["workout_id"] == 3001
    assert laps["count"] == 2
    assert laps["total"] == 2
    assert laps["truncated"] is False
    assert isinstance(laps["rows"][0]["duration_min"], float)


def test_mcp_workout_calendar_and_health_families_replay_offline(
    replay_backend: Path,
) -> None:
    server = create_mcp_server(_config(garth_home=str(replay_backend)))

    workouts = _call(server, "workout_list", {"limit": 20})
    workout = _call(server, "workout_get", {"workout_id": 3001})
    calendar = _call(
        server,
        "workout_calendar",
        {"start_date": "2026-07-01", "end_date": "2026-07-05"},
    )
    steps = _call(
        server,
        "health_steps",
        {"start_date": "2026-07-01", "end_date": "2026-07-03"},
    )
    body_battery = _call(
        server,
        "health_body_battery",
        {"start_date": "2026-07-01", "end_date": "2026-07-01"},
    )
    hrv = _call(
        server,
        "health_hrv",
        {"start_date": "2026-07-01", "end_date": "2026-07-01"},
    )
    weight = _call(
        server,
        "health_weight",
        {"start_date": "2026-07-01", "end_date": "2026-07-01"},
    )
    stress = _call(
        server,
        "health_stress",
        {"start_date": "2026-07-01", "end_date": "2026-07-01"},
    )
    spo2 = _call(
        server,
        "health_spo2",
        {"start_date": "2026-07-01", "end_date": "2026-07-01"},
    )
    readiness = _call(
        server,
        "health_readiness",
        {"start_date": "2026-07-01", "end_date": "2026-07-01"},
    )
    status = _call(server, "health_training_status", {"date": "2026-07-01"})

    assert workouts["rows"][0]["sport"] == "running"
    assert workout["rows"][0]["write_compatible"] is True
    assert calendar["rows"][0]["workout_id"] == 3001
    assert calendar["rows"][0]["workout_schedule_id"] == 4001
    assert steps["count"] == 3
    assert body_battery["rows"][0]["max_level"] == 78
    assert hrv["rows"][0]["status"] == "BALANCED"
    assert isinstance(weight["rows"][0]["weight_kg"], float)
    assert stress["rows"][0]["avg_stress"] == 28
    assert spo2["rows"][0]["avg_spo2"] == 96
    assert readiness["rows"][0]["score"] == 78
    assert status["count"] == 1
