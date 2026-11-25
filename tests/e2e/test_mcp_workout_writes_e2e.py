"""E2E tests for MCP workout write tools against the live Garmin Connect API.

Every test creates its own __e2e_workout_mcp_* workout, wraps the body in a
try/finally with a defensive workout_delete cleanup, and runs at the
rate_limiter's pace. A session-scoped orphan reaper deletes any leftover
__e2e_workout_mcp_* workouts after the suite finishes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from tests.helpers import require_mcp

require_mcp()

from garmin_cli.config import CliConfig  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402


E2E_WORKOUT_NAME_PREFIX = "__e2e_workout_mcp_"

_logger = logging.getLogger(__name__)


def make_e2e_workout_name(suffix: str | None = None) -> str:
    suffix = suffix or uuid.uuid4().hex[:8]
    return f"{E2E_WORKOUT_NAME_PREFIX}{suffix}"


def _minimal_workout(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "sport": "running",
        "steps": [
            {
                "type": "warmup",
                "duration": {"type": "time", "value": 300},
                "target": {"type": "no.target"},
            }
        ],
    }


def _call_tool_json(
    mcp_server: Any,
    rate_limiter: Any,
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    extra_delay: float = 0.0,
) -> dict[str, Any]:
    rate_limiter.wait(extra_delay)
    try:
        result = asyncio.run(mcp_server.call_tool(tool_name, args or {}))
    finally:
        rate_limiter.mark_complete()
    content_list = result[0] if isinstance(result, tuple) else result
    return json.loads(content_list[0].text)


def _assert_mcp_envelope_ok(parsed: dict[str, Any]) -> None:
    assert isinstance(parsed, dict)
    assert isinstance(parsed.get("count"), int)
    assert isinstance(parsed.get("rows"), list)
    assert parsed["count"] == len(parsed["rows"])


def _safe_delete(server: Any, rate_limiter: Any, workout_id: int | None) -> None:
    if workout_id is None:
        return
    try:
        _call_tool_json(
            server, rate_limiter, "workout_delete", {"workout_id": int(workout_id)},
        )
    except Exception as exc:  # noqa: BLE001 - teardown must not mask the real failure
        _logger.info("cleanup: workout_delete(%s) failed: %s", workout_id, exc)


@pytest.fixture(scope="module")
def mcp_server_live(garth_session):
    config = CliConfig(garth_home=garth_session)
    return create_mcp_server(config)


@pytest.fixture(scope="session", autouse=True)
def _orphan_workout_reaper(request):
    """At session teardown, delete any __e2e_workout_mcp_* workouts left behind."""
    yield
    # Build a server fresh for teardown so module fixtures don't tie us up.
    try:
        garth_home = request.getfixturevalue("garth_session")
    except pytest.FixtureLookupError:
        return

    config = CliConfig(garth_home=garth_home)
    server = create_mcp_server(config)
    try:
        parsed = asyncio.run(server.call_tool("workout_list", {"limit": 100}))
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "orphan reaper: workout_list failed -- skipping cleanup: %s", exc
        )
        return

    content_list = parsed[0] if isinstance(parsed, tuple) else parsed
    try:
        rows = json.loads(content_list[0].text).get("rows", [])
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "orphan reaper: could not parse workout_list -- skipping cleanup: %s", exc
        )
        return

    for row in rows:
        name = row.get("name") or ""
        if not name.startswith(E2E_WORKOUT_NAME_PREFIX):
            continue
        workout_id = row.get("id") or row.get("workoutId")
        _logger.info("orphan reaper: deleting %s (id=%s)", name, workout_id)
        try:
            asyncio.run(
                server.call_tool("workout_delete", {"workout_id": int(workout_id)})
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "orphan reaper: delete %s failed -- workout may remain on account: %s",
                workout_id,
                exc,
            )


@pytest.mark.e2e
def test_mcp_workout_full_lifecycle(mcp_server_live, rate_limiter):
    """AE1-AE4: dry_run -> create -> schedule -> update -> delete."""
    name = make_e2e_workout_name("lifecycle")
    workout = _minimal_workout(name)
    schedule_on = (date.today() + timedelta(days=90)).isoformat()

    # 1) Dry-run create returns a wire payload and makes no Garmin write.
    dry = _call_tool_json(
        mcp_server_live,
        rate_limiter,
        "workout_create",
        {"workout": workout, "dry_run": True},
    )
    _assert_mcp_envelope_ok(dry)
    dry_row = dry["rows"][0]
    assert dry_row["ok"] is True
    assert dry_row["dry_run"] is True
    assert "wire_payload" in dry_row
    assert dry_row["wire_payload"]["workoutName"] == name

    created_id: int | None = None
    try:
        # 2) Live create.
        created = _call_tool_json(
            mcp_server_live,
            rate_limiter,
            "workout_create",
            {"workout": workout},
        )
        _assert_mcp_envelope_ok(created)
        row = created["rows"][0]
        assert row["ok"] is True
        assert row["action"] == "created"
        created_id = row["workout_id"]
        assert isinstance(created_id, int)

        # 3) Schedule on a far-future date.
        scheduled = _call_tool_json(
            mcp_server_live,
            rate_limiter,
            "workout_schedule",
            {"workout_id": created_id, "date": schedule_on},
        )
        _assert_mcp_envelope_ok(scheduled)
        sched_row = scheduled["rows"][0]
        assert sched_row["ok"] is True
        assert sched_row["action"] == "scheduled"
        assert sched_row["workout_id"] == created_id

        # 4) Update (merge preserves lineage).
        updated_name = make_e2e_workout_name("lifecycle-renamed")
        updated = _call_tool_json(
            mcp_server_live,
            rate_limiter,
            "workout_update",
            {"workout_id": created_id, "workout": {"name": updated_name}},
        )
        _assert_mcp_envelope_ok(updated)
        upd_row = updated["rows"][0]
        assert upd_row["ok"] is True
        assert upd_row["action"] == "updated"
        assert upd_row["workout_id"] == created_id

        # 5) Verify rename and that workout_id is unchanged.
        fetched = _call_tool_json(
            mcp_server_live,
            rate_limiter,
            "workout_get",
            {"workout_id": created_id},
        )
        _assert_mcp_envelope_ok(fetched)
        if fetched["rows"]:
            assert fetched["rows"][0].get("name") == updated_name
            assert fetched["rows"][0].get("id") == created_id
    finally:
        _safe_delete(mcp_server_live, rate_limiter, created_id)


@pytest.mark.e2e
def test_mcp_workout_dry_run_does_not_persist(mcp_server_live, rate_limiter):
    """A pure dry-run create must NOT produce a workout visible in workout_list."""
    name = make_e2e_workout_name("dryonly")
    workout = _minimal_workout(name)

    _call_tool_json(
        mcp_server_live,
        rate_limiter,
        "workout_create",
        {"workout": workout, "dry_run": True},
    )

    listed = _call_tool_json(
        mcp_server_live, rate_limiter, "workout_list", {"limit": 50},
    )
    names = [row.get("name") for row in listed.get("rows", [])]
    assert name not in names, f"dry-run leaked a real workout named {name!r}"


@pytest.mark.e2e
def test_mcp_workout_update_dry_run_returns_merged_payload(
    mcp_server_live, rate_limiter,
):
    """Update dry-run does one read and returns the merged payload, no write."""
    name = make_e2e_workout_name("update-dry")
    workout = _minimal_workout(name)
    created_id: int | None = None
    try:
        created = _call_tool_json(
            mcp_server_live,
            rate_limiter,
            "workout_create",
            {"workout": workout},
        )
        created_id = created["rows"][0]["workout_id"]

        new_name = make_e2e_workout_name("update-dry-renamed")
        dry = _call_tool_json(
            mcp_server_live,
            rate_limiter,
            "workout_update",
            {
                "workout_id": created_id,
                "workout": {"name": new_name},
                "dry_run": True,
            },
        )
        row = dry["rows"][0]
        assert row["ok"] is True
        assert row["dry_run"] is True
        assert row["wire_payload"]["workoutName"] == new_name

        # Confirm the live workout still has its original name.
        fetched = _call_tool_json(
            mcp_server_live,
            rate_limiter,
            "workout_get",
            {"workout_id": created_id},
        )
        if fetched["rows"]:
            assert fetched["rows"][0].get("name") == name
    finally:
        _safe_delete(mcp_server_live, rate_limiter, created_id)
