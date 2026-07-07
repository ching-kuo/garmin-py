"""Shared / cross-cutting MCP tool tests (moved from test_mcp_server.py; assertions unchanged)."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


class TestToolRegistration:
    """Verify all expected tools are registered."""

    EXPECTED_TOOLS = frozenset({
        "health_sleep",
        "health_hrv",
        "health_weight",
        "health_daily_summary",
        "health_steps",
        "health_intensity_minutes",
        "health_body_battery",
        "health_stress",
        "health_spo2",
        "health_resting_hr",
        "health_readiness",
        "health_training_status",
        "activity_list",
        "activity_get",
        "activity_weather",
        "activity_laps",
        "activity_hr_zones",
        "activity_metrics_describe",
        "activity_detail_metrics",
        "activity_download",
        "activity_upload",
        "activity_delete",
        "activity_rename",
        "activity_set_type",
        "workout_list",
        "workout_get",
        "workout_calendar",
        "workout_create",
        "workout_schedule",
        "workout_update",
        "workout_delete",
        "workout_unschedule",
        "performance_thresholds",
        "performance_race_predictions",
        "performance_personal_records",
        "performance_endurance_score",
        "performance_hill_score",
        "performance_vo2max",
        "performance_zones",
        "device_list",
        "login_status",
        "report_snapshot",
    })

    def test_all_tools_registered(self) -> None:
        server = create_mcp_server(_config())
        tools = asyncio.run(server.list_tools())
        tool_names = {t.name for t in tools}
        assert tool_names == self.EXPECTED_TOOLS


class TestInputValidation:
    """Verify input validation raises ToolError."""

    def _server(self) -> Any:
        return create_mcp_server(_config())

    def test_invalid_date_format(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="Invalid date format"):
            _call(server, "health_sleep", {"start_date": "not-a-date", "end_date": "2026-01-07"})

    def test_date_range_exceeds_90_days(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="90 days"):
            _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-06-01"})

    def test_start_after_end(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="must be on or before"):
            _call(server, "health_sleep", {"start_date": "2026-03-10", "end_date": "2026-03-01"})

    def test_negative_limit(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="limit"):
            _call(server, "activity_list", {"limit": 0})

    def test_limit_over_100(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="limit"):
            _call(server, "activity_list", {"limit": 101})

    def test_negative_activity_id(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_get", {"activity_id": -1})

    def test_zero_activity_id(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_get", {"activity_id": 0})

    def test_negative_start_offset(self) -> None:

        server = self._server()
        with pytest.raises(ToolError, match="start"):
            _call(server, "activity_list", {"start": -1})


class TestErrorPropagation:

    def test_garmin_cli_error_becomes_tool_error(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_sleep", side_effect=GarminCliError(error="Rate limited by Garmin API.", error_code="RATE_LIMITED"))
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="Rate limited"):
            _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})

    def test_auth_missing_includes_login_hint(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated", side_effect=GarminCliError(error="No usable saved session found", error_code="AUTH_MISSING"))
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="garmin-cli login"):
            _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})

    def test_auth_failed_no_login_hint(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated", side_effect=GarminCliError(error="garth_home path is a symlink", error_code="AUTH_FAILED"))
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="symlink") as exc_info:
            _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert "garmin-cli login" not in str(exc_info.value)


class TestEnvelopeShape:
    """All tools must return {"count": N, "rows": [...]}."""

    def test_envelope_has_count_and_rows(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_sleep", return_value=[])
        server = create_mcp_server(_config())
        result = _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        assert "count" in result
        assert "rows" in result
        assert isinstance(result["rows"], list)
        assert result["count"] == len(result["rows"])

    def test_empty_result_envelope(self, mocker: Any) -> None:

        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.activities.list_activities", return_value=[])
        server = create_mcp_server(_config())
        result = _call(server, "activity_list", {"limit": 10})
        assert result == {"count": 0, "rows": []}


class TestConfigPassthrough:

    def test_garth_home_reaches_auth(self, mocker: Any) -> None:

        mock_auth = mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.health.get_sleep", return_value=[])
        config = _config(garth_home="/custom/garth")
        server = create_mcp_server(config)
        _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        passed_config = mock_auth.call_args[0][0]
        assert passed_config.garth_home == "/custom/garth"


class TestImportGuard:

    def test_mcp_import_error_shows_message(self, mocker: Any) -> None:
        from click.testing import CliRunner
        from garmin_cli.cli import cli

        mocker.patch.dict("sys.modules", {"garmin_cli.mcp_server": None})
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["mcp-server"])
        assert result.exit_code == 1
        assert 'pip install "garmin-cli[mcp]"' in (result.output + (result.stderr or ""))


class TestCollectReportSections:
    """Unit-test the per-section fan-out / isolation helper directly."""

    def test_ok_sections_collected(self) -> None:
        from garmin_cli.mcp_tools._shared import _collect_report_sections

        specs = [
            ("a", lambda: [1], lambda raw: [{"v": 1}]),
            ("b", lambda: [2], lambda raw: [{"v": 2}]),
        ]
        sections, unavailable = _collect_report_sections(specs)
        assert sections == {"a": [{"v": 1}], "b": [{"v": 2}]}
        assert unavailable == []

    def test_empty_section_marked_no_data(self) -> None:
        from garmin_cli.mcp_tools._shared import _collect_report_sections

        specs = [("a", lambda: [], lambda raw: [])]
        sections, unavailable = _collect_report_sections(specs)
        assert sections == {"a": []}
        assert unavailable == [{"section": "a", "reason": "no_data"}]

    def test_not_found_isolated(self) -> None:
        from garmin_cli.mcp_tools._shared import _collect_report_sections

        def boom() -> Any:
            raise GarminCliError(error="missing", error_code="NOT_FOUND")

        specs = [
            ("a", boom, lambda raw: [{"v": 1}]),
            ("b", lambda: [2], lambda raw: [{"v": 2}]),
        ]
        sections, unavailable = _collect_report_sections(specs)
        assert sections == {"a": [], "b": [{"v": 2}]}
        assert unavailable == [{"section": "a", "reason": "not_found"}]

    def test_fatal_error_propagates(self) -> None:
        from garmin_cli.mcp_tools._shared import _collect_report_sections

        def rate_limited() -> Any:
            raise GarminCliError(error="slow down", error_code="RATE_LIMITED")

        specs = [("a", rate_limited, lambda raw: [{"v": 1}])]
        with pytest.raises(GarminCliError) as exc:
            _collect_report_sections(specs)
        assert exc.value.error_code == "RATE_LIMITED"
