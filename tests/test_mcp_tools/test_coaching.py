"""Contract tests for the bounded coach snapshot MCP tool."""

from __future__ import annotations

from datetime import date as Date
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


def _tool_annotations(server: Any, name: str) -> Any:
    return server._tool_manager.get_tool(name).annotations


class TestCoachSnapshot:
    def test_read_only_annotation(self) -> None:
        annotations = _tool_annotations(create_mcp_server(_config()), "coach_snapshot")
        assert annotations is not None
        assert annotations.read_only_hint is True

    def test_terminal_rate_limit_preserves_prior_sections_and_stops(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        sleep = mocker.patch("garmin_cli.services.coaching_snapshot.get_sleep", return_value={})
        hrv = mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_hrv",
            side_effect=GarminCliError("slow down", "RATE_LIMITED"),
        )
        body_battery = mocker.patch("garmin_cli.services.coaching_snapshot.get_body_battery_range")
        server = create_mcp_server(_config())

        result = _call(server, "coach_snapshot", {"date": "2026-07-15"})

        assert result["complete"] is False
        assert result["aborted"] is True
        assert result["errors"] == [
            {
                "section": "hrv",
                "error_code": "RATE_LIMITED",
                "category": "rate_limit",
                "message": "Garmin data for this section was unavailable.",
                "recovery_hint": "Retry the snapshot later; do not retry immediately.",
            }
        ]
        assert result["provenance"]["completed_requests"] == 1
        auth.assert_called_once()
        sleep.assert_called_once()
        hrv.assert_called_once()
        body_battery.assert_not_called()

    def test_extended_baseline_above_budget_fails_before_auth(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        server = create_mcp_server(_config())

        with pytest.raises(Exception, match="request budget"):
            _call(
                server,
                "coach_snapshot",
                {"date": "2026-07-15", "include_extended_daily_baselines": True},
            )
        auth.assert_not_called()

    def test_steps_window_is_capped_at_28_dates(self, mocker: Any) -> None:
        """Garmin's daily-steps endpoint 400s on spans wider than 28 dates."""
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        steps = mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_steps_range", return_value=[]
        )
        mocker.patch(
            "garmin_cli.services.coaching_snapshot.get_weight",
            side_effect=GarminCliError("stop early", "RATE_LIMITED"),
        )
        for name in ("get_sleep", "get_hrv", "get_body_battery_range"):
            mocker.patch(
                f"garmin_cli.services.coaching_snapshot.{name}", return_value=[]
            )
        server = create_mcp_server(_config())

        _call(server, "coach_snapshot", {"date": "2026-07-15"})

        steps.assert_called_once_with(Date(2026, 6, 18), Date(2026, 7, 15))
