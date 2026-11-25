"""MCP write audit log: exactly one JSON line per write-tool call, metadata only."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError  # noqa: E402
from mcp_types import CallToolRequestParams  # noqa: E402

from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from garmin_cli.mcp_tools import _audit  # noqa: E402
from garmin_cli.mcp_tools._audit import WriteLogEvent, _emit_audit, _write_audit  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402

_PLAN = {
    "name": "Block",
    "start_date": "2026-07-01",
    "end_date": "2026-07-07",
    "entries": [{"entry_id": "a", "date": "2026-07-02", "workout_id": 10}],
}


@pytest.fixture()
def lines() -> Iterator[list[dict[str, Any]]]:
    """Collect audit events directly, whatever handler the process configured."""
    collected: list[dict[str, Any]] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            collected.append(json.loads(record.getMessage()))

    logger = logging.getLogger("garmin_cli.audit")
    handler, level = _Collect(), logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield collected
    logger.removeHandler(handler)
    logger.setLevel(level)


@pytest.fixture()
def server(lines: list[dict[str, Any]]) -> Any:
    return create_mcp_server(_config())


def test_write_event_is_one_json_line_without_names(mocker: Any, lines: list[Any], server: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools.activities_write.ensure_authenticated")
    mocker.patch("garmin_cli.mcp_tools.activities_write.set_activity_name")
    _call(server, "activity_rename", {"activity_id": 5, "name": "Secret ride"})
    assert lines == [{"activity_id": 5, "name_len": 11, "outcome": "success", "tool": "activity_rename"}]


def test_unexpected_exception_records_a_failure(mocker: Any, lines: list[Any], server: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
    mocker.patch("garmin_cli.mcp_tools.workouts.delete_workout", side_effect=RuntimeError("bug"))
    with pytest.raises(UnexpectedToolError):
        _call(server, "workout_delete", {"workout_id": 3})
    assert [line["outcome"] for line in lines] == ["failed-upstream"]


def test_result_conversion_failure_after_the_body_logs_once(mocker: Any, lines: list[Any], server: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
    mocker.patch("garmin_cli.mcp_tools.workouts.unschedule_workout")
    mocker.patch("garmin_cli.mcp_tools.workouts._envelope", return_value={"count": object()})
    with pytest.raises(UnexpectedToolError):
        _call(server, "workout_unschedule", {"schedule_id": 77})
    assert lines == [{"outcome": "success", "schedule_id": 77, "tool": "workout_unschedule"}]


def test_local_tool_error_inside_the_audit_is_a_validation_failure(lines: list[Any]) -> None:
    with pytest.raises(ToolError), _write_audit(WriteLogEvent(tool="t", outcome="success"), _emit_audit):
        raise ToolError("bad local input")
    assert lines == [{"outcome": "failed-validation", "tool": "t"}]


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("workout_create", {"workout": {"name": "x"}}),
        ("workout_delete", {"workout_id": 0}),
        ("workout_schedule", {"workout_id": 1, "date": "not-a-date"}),
        ("activity_rename", {"activity_id": "5", "name": "Secret"}),
    ],
)
def test_calls_rejected_before_the_tool_body_log_tool_and_outcome_only(
    lines: list[Any], server: Any, tool: str, args: dict[str, Any]
) -> None:
    with pytest.raises(ToolError):
        _call(server, tool, args)
    assert lines == [{"outcome": "failed-validation", "tool": tool}]


def test_read_tool_rejections_are_not_audited(lines: list[Any], server: Any) -> None:
    with pytest.raises(ToolError):
        _call(server, "activity_get", {"activity_id": 0})
    assert lines == []


def test_unregistered_write_tool_in_read_only_mode_is_not_audited(lines: list[Any]) -> None:
    server = create_mcp_server(_config(), read_only=True)
    with pytest.raises(ToolError, match="Unknown tool"):
        _call(server, "workout_delete", {"workout_id": 3})
    assert lines == []


def test_set_type_logs_the_key_only_after_garmin_accepted_it(mocker: Any, lines: list[Any], server: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools.activities_write.ensure_authenticated")
    set_type = mocker.patch("garmin_cli.mcp_tools.activities_write.set_activity_type")
    _call(server, "activity_set_type", {"activity_id": 5, "type_key": "Running"})
    set_type.side_effect = GarminCliError("unknown type key", "INVALID_INPUT")
    with pytest.raises(ToolError):
        _call(server, "activity_set_type", {"activity_id": 5, "type_key": "my secret note"})
    assert lines == [
        {"activity_id": 5, "outcome": "success", "tool": "activity_set_type", "type_key": "running"},
        {"activity_id": 5, "outcome": "failed-validation", "tool": "activity_set_type", "type_key_len": 14},
    ]


def test_unschedule_logs_schedule_id(mocker: Any, lines: list[Any], server: Any) -> None:
    mocker.patch("garmin_cli.mcp_tools.workouts.ensure_authenticated")
    mocker.patch("garmin_cli.mcp_tools.workouts.unschedule_workout")
    _call(server, "workout_unschedule", {"schedule_id": 77})
    assert lines == [{"outcome": "success", "schedule_id": 77, "tool": "workout_unschedule"}]


def test_upload_rejected_by_garmin_is_not_a_success(
    mocker: Any, lines: list[Any], server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(tmp_path))
    (tmp_path / "ride.fit").write_bytes(b"FIT")
    mocker.patch("garmin_cli.mcp_tools.activities_write.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.activities_write.upload_activity",
        return_value={"detailedImportResult": {"successes": [], "failures": [{"messages": []}]}},
    )
    assert _call(server, "activity_upload", {"file_path": "ride.fit"})["rows"][0]["status"] == "rejected"
    assert [line["outcome"] for line in lines] == ["rejected"]


@pytest.mark.parametrize(
    ("result", "outcome"),
    [
        ({"outcome": "compensated", "operations": [{"state": "compensated"}], "errors": [{"error_code": "SERVER_ERROR"}]},
         "failed-upstream"),
        ({"outcome": "partial", "operations": [{"state": "planned"}], "errors": [],
          "conflicts": [{"reason": "destination_occupied"}]}, "conflict"),
        # The live recheck found the destination occupied before any write.
        ({"outcome": "compensated", "operations": [{"action": "apply", "state": "failed", "error_code": "INVALID_INPUT"}],
          "errors": [{"error_code": "INVALID_INPUT", "message": "Plan application did not complete."}],
          "conflicts": []}, "conflict"),
    ],
)
def test_plan_apply_records_the_plan_outcome(
    mocker: Any, lines: list[Any], server: Any, result: dict[str, Any], outcome: str
) -> None:
    mocker.patch("garmin_cli.mcp_tools.training_plan.ensure_authenticated")
    mocker.patch("garmin_cli.mcp_tools.training_plan.apply_training_plan", return_value=result)
    _call(server, "training_plan_apply", {"plan": _PLAN})
    assert [(line["outcome"], line["plan_outcome"]) for line in lines] == [(outcome, result["outcome"])]


def test_reschedule_and_mfa_are_audited_once(mocker: Any, lines: list[Any], server: Any) -> None:
    mocker.patch(
        "garmin_cli.mcp_tools.training_plan.ensure_authenticated",
        side_effect=GarminCliError("no session", "AUTH_MISSING"),
    )
    mocker.patch(
        "garmin_cli.mcp_tools.misc.complete_mfa_login",
        side_effect=GarminCliError("bad code", "AUTH_FAILED"),
    )
    args = {"schedule_id": 9, "new_date": "2026-07-03", "expected_date": "2026-07-02"}
    with pytest.raises(ToolError):
        _call(server, "training_plan_reschedule", args)
    with pytest.raises(ToolError):
        _call(server, "submit_mfa_code", {"mfa_code": "123456"})
    assert [(line["tool"], line["outcome"]) for line in lines] == [
        ("training_plan_reschedule", "failed-auth"),
        ("submit_mfa_code", "failed-auth"),
    ]
    assert lines[0]["schedule_id"] == 9
    assert "123456" not in json.dumps(lines)


def test_rejected_arguments_never_reach_stderr_on_the_wire_path(
    mocker: Any, server: Any, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)  # a host that logs INFO must still not see argument text
    mocker.patch("garmin_cli.mcp_tools.activities_write.ensure_authenticated")
    mocker.patch(
        "garmin_cli.mcp_tools.activities_write.set_activity_type",
        side_effect=GarminCliError("unknown type key 'my-secret-sport'", "INVALID_INPUT"),
    )
    calls = [
        ("activity_set_type", {"activity_id": 5, "type_key": "my-secret-sport"}),
        ("workout_schedule", {"workout_id": 1, "date": "secret-date-text"}),
        ("activity_upload", {"file_path": "/private/secret/path.fit"}),
    ]
    for name, arguments in calls:
        result = asyncio.run(server._handle_call_tool(None, CallToolRequestParams(name=name, arguments=arguments)))
        assert result.is_error is True or name == "activity_upload"
    logged = capsys.readouterr().err + "\n".join(record.getMessage() for record in caplog.records)
    for secret in ("my-secret-sport", "secret-date-text", "/private/secret/path.fit"):
        assert secret not in logged


class TestAuditLoggingSetup:
    @pytest.fixture()
    def fresh_logger(self) -> Iterator[logging.Logger]:
        logger = logging.getLogger("garmin_cli.audit")
        saved = (list(logger.handlers), logger.propagate, logger.level)
        logger.handlers = []
        logger.propagate, logger.level = True, logging.NOTSET
        yield logger
        logger.handlers, logger.propagate, logger.level = saved[0], saved[1], saved[2]

    def test_host_root_handlers_keep_propagation(self, fresh_logger: logging.Logger) -> None:
        root = logging.getLogger()
        host = logging.NullHandler()
        root.addHandler(host)
        try:
            _audit.configure_audit_logging()
        finally:
            root.removeHandler(host)
        assert fresh_logger.handlers == []
        assert fresh_logger.propagate is True
        assert fresh_logger.level == logging.INFO

    def test_unconfigured_process_gets_a_private_stderr_handler(
        self, fresh_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(logging.getLogger(), "handlers", [])
        _audit.configure_audit_logging()
        assert [type(handler).__name__ for handler in fresh_logger.handlers] == ["_StderrHandler"]
        assert fresh_logger.propagate is False
