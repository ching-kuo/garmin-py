"""Shared / cross-cutting MCP tool tests (moved from test_mcp_server.py; assertions unchanged)."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from garmin_cli.mcp_tools._shared import _envelope  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


_ID_TOOLS = [
    ("activity_get", "activity_id", {}),
    ("activity_weather", "activity_id", {}),
    ("activity_laps", "activity_id", {}),
    ("activity_hr_zones", "activity_id", {}),
    ("activity_metrics_describe", "activity_id", {}),
    ("activity_detail_metrics", "activity_id", {}),
    ("activity_download", "activity_id", {}),
    ("activity_delete", "activity_id", {}),
    ("activity_rename", "activity_id", {"name": "x"}),
    ("activity_set_type", "activity_id", {"type_key": "running"}),
    ("workout_get", "workout_id", {}),
    ("workout_schedule", "workout_id", {"date": "2026-03-11"}),
    ("workout_update", "workout_id", {"workout": {"name": "x"}}),
    ("workout_delete", "workout_id", {}),
    ("workout_unschedule", "schedule_id", {}),
    ("training_plan_reschedule", "schedule_id", {"new_date": "2026-03-12", "expected_date": "2026-03-11"}),
]


@pytest.mark.parametrize(("tool", "id_arg", "extra"), _ID_TOOLS)
@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_id_parameters_reject_coercible_non_ints_at_schema_validation(
    mocker: Any, tool: str, id_arg: str, extra: dict[str, Any], value: Any
) -> None:
    # A coerced id must never reach auth or a (destructive) handler.
    reached = RuntimeError("handler reached")
    for module in ("_shared", "workouts", "activities_write"):
        mocker.patch(f"garmin_cli.mcp_tools.{module}.ensure_authenticated", side_effect=reached)
    server = create_mcp_server(_config())

    with pytest.raises(ToolError) as exc_info:
        _call(server, tool, {id_arg: value, **extra})
    assert "handler reached" not in str(exc_info.value)
    assert id_arg in str(exc_info.value)


@pytest.mark.parametrize("value", [True, False, 1.0, 2.5, 0, -3, "7"])
def test_validate_positive_id_rejects_non_int_and_non_positive(value: Any) -> None:
    from garmin_cli.mcp_tools._shared import _validate_positive_id

    with pytest.raises(ToolError, match="positive integer"):
        _validate_positive_id(value, "activity_id")


@pytest.mark.parametrize(
    "value", [True, 1.0, 2.5, 0, -3, "-3", "abc", None, " 12\n", "+12", "1_2", "١٢", "0", "9" * 21, "9" * 5000]
)
def test_validate_numeric_id_rejects_bool_float_and_non_positive(value: Any) -> None:
    from garmin_cli.endpoints._base import _validate_numeric_id

    with pytest.raises(GarminCliError) as exc_info:
        _validate_numeric_id(value, "activity_id")
    assert exc_info.value.error_code == "INVALID_INPUT"


def test_validate_numeric_id_accepts_ints_and_digit_strings() -> None:
    from garmin_cli.endpoints._base import _validate_numeric_id

    assert _validate_numeric_id(12, "activity_id") == 12
    assert _validate_numeric_id("12", "activity_id") == 12


def test_envelope_without_cap_preserves_legacy_shape() -> None:
    rows = [{"id": 1}, {"id": 2}]

    assert _envelope(rows) == {"count": 2, "rows": rows}


def test_envelope_cap_pages_and_sets_next_offset() -> None:
    rows = [{"id": value} for value in range(300)]

    first = _envelope(rows, cap=100)
    second = _envelope(rows, cap=100, offset=100)
    final = _envelope(rows, cap=100, offset=200)

    assert first == {
        "count": 100,
        "rows": rows[:100],
        "total": 300,
        "truncated": True,
        "next_offset": 100,
    }
    assert second["rows"] == rows[100:200]
    assert second["next_offset"] == 200
    assert final == {
        "count": 100,
        "rows": rows[200:],
        "total": 300,
        "truncated": False,
    }


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
        "performance_ftp_history",
        "performance_acclimation",
        "performance_cycling_ability",
        "performance_power_curve",
        "performance_fastest_splits",
        "device_list",
        "login_status",
        "server_doctor",
        "submit_mfa_code",
        "report_snapshot",
        "coach_snapshot",
        "training_plan_reconcile",
        "training_plan_preview",
        "training_plan_apply",
        "training_plan_reschedule",
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

    def test_error_text_has_machine_readable_metadata(
        self,
        mocker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("GARMIN_CLI_RETRY_DELAYS", raising=False)
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch(
            "garmin_cli.mcp_tools.health.get_sleep",
            side_effect=GarminCliError(error="Rate limited by Garmin API.", error_code="RATE_LIMITED"),
        )
        server = create_mcp_server(_config())
        with pytest.raises(ToolError) as exc_info:
            _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        payload = json.loads(str(exc_info.value).split(": ", 1)[1])
        assert payload["error_code"] == "RATE_LIMITED"
        assert payload["category"] == "rate_limit"
        assert "retry" in payload["recovery_hint"].lower()
        assert payload["retry_after_seconds"] == 2

    def test_login_backoff_reports_its_own_retry_after(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.mcp_tools._shared.ensure_authenticated",
            side_effect=GarminCliError(
                error="Authentication failed.", error_code="AUTH_FAILED", retry_after_seconds=42
            ),
        )
        server = create_mcp_server(_config())
        with pytest.raises(ToolError) as exc_info:
            _call(server, "health_sleep", {"start_date": "2026-01-01", "end_date": "2026-01-01"})
        payload = json.loads(str(exc_info.value).split(": ", 1)[1])
        assert payload["retry_after_seconds"] == 42

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
        assert 'pip install "garmin-py[mcp]"' in (result.output + (result.stderr or ""))


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
