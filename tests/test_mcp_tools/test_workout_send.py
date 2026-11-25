"""MCP `workout_send_to_device` tests (Garmin write: mocked, never live)."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.helpers import EDGE, EDGE_1040, FENIX, make_http_error, require_mcp, workout

require_mcp()

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli.endpoints.workouts import send_workout_to_device as endpoint_send  # noqa: E402
from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config, _tool_annotations  # noqa: E402


def _patch(mocker: Any, devices: list[dict[str, Any]], sport: str = "running") -> tuple[Any, Any]:
    mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
    mocker.patch("garmin_cli.services.workouts.get_workout", return_value=workout(sport))
    mocker.patch("garmin_cli.services.workouts.get_devices", return_value=devices)
    send = mocker.patch("garmin_cli.mcp_tools.workouts.send_workout_to_device", return_value=None)
    log = mocker.patch("garmin_cli.mcp_tools.workouts._emit_write_log")
    return send, log


def _send(args: dict[str, Any]) -> Any:
    return _call(create_mcp_server(_config()), "workout_send_to_device", args)


def test_sends_to_the_device_that_takes_the_sport_and_audits(mocker: Any) -> None:
    send, log = _patch(mocker, [FENIX, EDGE])

    row = _send({"workout_id": 123})["rows"][0]

    assert row == {
        "ok": True, "action": "sent", "workout_id": 123, "workout_name": "Tempo",
        "device_id": 11, "display_name": "fenix 8",
    }
    send.assert_called_once_with(123, "Tempo", 11)
    event = log.call_args.args[0]
    assert (event.tool, event.outcome, event.workout_id, event.device_id) == (
        "workout_send_to_device", "success", 123, 11,
    )


def test_auto_resolved_dry_run_does_not_send_and_logs_the_device(mocker: Any) -> None:
    send, log = _patch(mocker, [FENIX, EDGE], sport="running")

    row = _send({"workout_id": 123, "dry_run": True})["rows"][0]

    assert row["dry_run"] is True and row["device_id"] == 11
    send.assert_not_called()
    event = log.call_args.args[0]
    assert (event.outcome, event.device_id) == ("dry-run", 11)


def test_failed_send_logs_the_device_and_warns_it_may_be_queued(mocker: Any) -> None:
    _, log = _patch(mocker, [FENIX])
    mocker.patch("garmin_cli.mcp_tools.workouts.send_workout_to_device", endpoint_send)
    garth = mocker.patch("garmin_cli.endpoints.workouts.garth")
    garth.send_workout_message.side_effect = make_http_error(503)

    with pytest.raises(ToolError, match="may already be queued"):
        _send({"workout_id": 123})

    event = log.call_args.args[0]
    assert (event.outcome, event.device_id) == ("failed-upstream", 11)
    garth.send_workout_message.assert_called_once()


def test_ambiguous_device_is_a_validation_failure(mocker: Any) -> None:
    send, log = _patch(mocker, [FENIX, EDGE, EDGE_1040], sport="cycling")

    with pytest.raises(ToolError, match="11 \\(fenix 8\\), 22 \\(Edge 850\\), 23 \\(Edge 1040\\)"):
        _send({"workout_id": 123})

    send.assert_not_called()
    assert log.call_args.args[0].outcome == "failed-validation"


def test_explicit_device_is_used(mocker: Any) -> None:
    send, log = _patch(mocker, [FENIX, EDGE], sport="cycling")

    assert _send({"workout_id": 123, "device_id": 22})["rows"][0]["display_name"] == "Edge 850"
    send.assert_called_once_with(123, "Tempo", 22)
    assert log.call_args.args[0].device_id == 22


def test_incapable_explicit_device_is_a_validation_failure_logging_the_device(mocker: Any) -> None:
    send, log = _patch(mocker, [FENIX, EDGE], sport="running")

    with pytest.raises(ToolError, match="Device 22 cannot receive running workouts"):
        _send({"workout_id": 123, "device_id": 22})

    send.assert_not_called()
    event = log.call_args.args[0]
    assert (event.outcome, event.device_id) == ("failed-validation", 22)


def test_dry_run_of_a_missing_workout_is_not_found(mocker: Any) -> None:
    send, log = _patch(mocker, [FENIX])
    mocker.patch(
        "garmin_cli.services.workouts.get_workout",
        side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
    )

    with pytest.raises(ToolError, match="NOT_FOUND"):
        _send({"workout_id": 999, "dry_run": True})

    send.assert_not_called()
    assert log.call_args.args[0].outcome == "failed-upstream"


def test_annotated_as_a_non_idempotent_write() -> None:
    ann = _tool_annotations(create_mcp_server(_config()), "workout_send_to_device")
    assert ann.destructive_hint is True
    assert ann.idempotent_hint is False


def test_removed_in_read_only_mode() -> None:
    tools = {tool.name for tool in asyncio.run(create_mcp_server(_config(), read_only=True).list_tools())}
    assert "workout_send_to_device" not in tools
