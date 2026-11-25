"""CLI tests for the `plan` group (Garmin writes mocked, never live)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli
from tests.helpers import require_mcp

PLAN = {
    "name": "July block",
    "start_date": "2026-07-01",
    "end_date": "2026-07-14",
    "entries": [{"entry_id": "run-1", "date": "2026-07-10", "workout_id": 10}],
}
PLAN_YAML = """\
name: July block
start_date: 2026-07-01
end_date: 2026-07-14
entries:
  - entry_id: run-1
    date: 2026-07-10
    workout_id: 10
"""
# Garmin calendar row already holding the plan's workout: preview keeps it.
CALENDAR_RAW = [{"date": "2026-07-10", "workoutId": 10, "workoutScheduleId": 99}]
WORKOUT_RAW = {"workoutId": 10, "workoutName": "Run", "sportType": {"sportTypeKey": "running"}, "workoutSegments": []}
APPLIED = {
    "complete": True,
    "outcome": "complete",
    "operations": [{"entry_id": "run-1", "action": "schedule", "state": "verified", "date": "2026-07-10",
                    "workout_id": 10, "workout_schedule_id": 1001}],
    "errors": [],
    "conflicts": [],
}
ROLLED_BACK = {
    "complete": False,
    "outcome": "compensated",
    "operations": [{"action": "unschedule", "schedule_id": 1001, "state": "compensated"}],
    "errors": [{"error_code": "SERVER_ERROR", "message": "Source unschedule did not complete."}],
    "conflicts": [],
}


def _invoke(args: list[str], stdin: str | None = None) -> Any:
    return CliRunner(mix_stderr=False).invoke(cli, args, input=stdin)


def _plan_file(tmp_path: Path, plan: dict[str, Any] = PLAN) -> str:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    return str(path)


def _patch_calendar(mocker: Any) -> None:
    mocker.patch("garmin_cli.services.schedule_writes.get_calendar_range", return_value=CALENDAR_RAW)
    mocker.patch("garmin_cli.services.plan_apply.get_workout", return_value=WORKOUT_RAW)


class TestYamlDates:

    def test_shared_anchor_converts_once_and_stays_shared(self) -> None:
        from garmin_cli.commands.plan import _dates_to_strings

        shared = {"expected_date": date(2026, 7, 9)}
        converted = _dates_to_strings({"a": shared, "b": [shared]})
        assert converted["a"] == {"expected_date": "2026-07-09"}
        assert converted["b"][0] is converted["a"]

    def test_nested_aliases_do_not_blow_up(self) -> None:
        from garmin_cli.commands.plan import _dates_to_strings

        lines = ["l0: &l0 [2026-07-10, 2026-07-10]"]
        lines += [f"l{n}: &l{n} [*l{n - 1}, *l{n - 1}]" for n in range(1, 13)]
        import yaml

        converted = _dates_to_strings(yaml.safe_load("\n".join(lines)))
        assert converted["l0"] == ["2026-07-10", "2026-07-10"]
        assert converted["l12"][0] is converted["l12"][1] is converted["l11"]

    def test_shared_inline_workout_anchor_previews(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch("garmin_cli.services.schedule_writes.get_calendar_range", return_value=[])
        mocker.patch("garmin_cli.services.plan_apply.get_workout", return_value=WORKOUT_RAW)
        yaml_text = (
            "name: Shared\nstart_date: 2026-07-01\nend_date: 2026-07-14\nentries:\n"
            "  - {entry_id: a, date: 2026-07-10, workout: &w {name: Easy, sport: running,"
            " steps: [{type: warmup, duration: {type: time, value: 600}}]}}\n"
            "  - {entry_id: b, date: 2026-07-11, workout: *w}\n"
        )
        result = _invoke(["--json", "plan", "preview", "-", "--input-format", "yaml"], stdin=yaml_text)
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["data"][0]["summary"] == {"scheduled_count": 2, "template_count": 2}

    def test_timestamp_in_a_string_field_is_rejected(self, mocker: Any) -> None:
        auth = mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        yaml_text = PLAN_YAML.replace("date: 2026-07-10", "date: 2026-07-10 08:00:00")
        result = _invoke(["--json", "plan", "preview", "-", "--input-format", "yaml"], stdin=yaml_text)
        envelope = json.loads(result.stdout)
        assert envelope["error_code"] == "INVALID_INPUT"
        assert "plan.entries[0].date must be YYYY-MM-DD" in envelope["error"]
        auth.assert_not_called()


class TestPreview:

    def test_trailing_json_after_file(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        _patch_calendar(mocker)
        result = _invoke(["plan", "preview", _plan_file(tmp_path), "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["command"] == "plan preview"

    def test_table_escapes_control_characters_json_keeps_them(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        _patch_calendar(mocker)
        plan = {**PLAN, "entries": [{**PLAN["entries"][0], "entry_id": "run\x1b[2K"}]}
        table = _invoke(["plan", "preview", _plan_file(tmp_path, plan)])
        assert "\x1b" not in table.stdout and "run\\x1b[2K" in table.stdout
        as_json = _invoke(["--json", "plan", "preview", _plan_file(tmp_path, plan)])
        assert json.loads(as_json.stdout)["data"][0]["operations"][0]["entry_id"] == "run\x1b[2K"

    def test_json_file_returns_the_service_diff(self, mocker: Any, tmp_path: Path) -> None:
        auth = mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        _patch_calendar(mocker)
        result = _invoke(["--json", "plan", "preview", _plan_file(tmp_path)])
        assert result.exit_code == 0, result.output
        envelope = json.loads(result.stdout)
        assert envelope["command"] == "plan preview"
        assert envelope["data"][0]["operations"][0]["action"] == "keep"
        auth.assert_called_once()

    def test_yaml_stdin_with_unquoted_dates(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        _patch_calendar(mocker)
        result = _invoke(["plan", "preview", "-", "--input-format", "yaml"], stdin=PLAN_YAML)
        assert result.exit_code == 0, result.stderr
        assert "keep" in result.stdout
        assert "complete: true" in result.stdout

    def test_conflict_exits_1_with_the_result(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch(
            "garmin_cli.services.schedule_writes.get_calendar_range",
            return_value=[{"date": "2026-07-10", "workoutId": 77, "workoutScheduleId": 5}],
        )
        mocker.patch("garmin_cli.services.plan_apply.get_workout", return_value=WORKOUT_RAW)
        result = _invoke(["plan", "preview", _plan_file(tmp_path)])
        assert result.exit_code == 1
        assert "destination_occupied" in result.stdout

    def test_invalid_plan_is_invalid_input_before_auth(self, mocker: Any, tmp_path: Path) -> None:
        auth = mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        result = _invoke(["--json", "plan", "preview", _plan_file(tmp_path, {**PLAN, "entries": []})])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error_code"] == "INVALID_INPUT"
        assert "at least one entry or removal" in envelope["error"]
        auth.assert_not_called()

    def test_missing_file_is_invalid_input(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        result = _invoke(["--json", "plan", "preview", str(tmp_path / "nope.json")])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_code"] == "INVALID_INPUT"

    @pytest.mark.parametrize("command", [
        ["preview", "PLAN"],
        ["apply", "PLAN", "--yes"],
        ["reschedule", "--schedule-id", "42", "--new-date", "2026-07-12", "--expected-date", "2026-07-10", "--yes"],
    ])
    def test_csv_is_refused(self, mocker: Any, tmp_path: Path, command: list[str]) -> None:
        auth = mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        args = [_plan_file(tmp_path) if arg == "PLAN" else arg for arg in command]
        result = _invoke(["--format", "csv", "plan", *args])
        assert result.exit_code == 1
        assert "--json" in result.stderr
        auth.assert_not_called()

    def test_incomplete_json_result_is_ok_envelope_with_exit_1(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch(
            "garmin_cli.services.schedule_writes.get_calendar_range",
            return_value=[{"date": "2026-07-10", "workoutId": 77, "workoutScheduleId": 5}],
        )
        mocker.patch("garmin_cli.services.plan_apply.get_workout", return_value=WORKOUT_RAW)
        result = _invoke(["--json", "plan", "preview", _plan_file(tmp_path)])
        envelope = json.loads(result.stdout)
        assert (result.exit_code, envelope["ok"], envelope["data"][0]["complete"]) == (1, True, False)

    @pytest.mark.parametrize(("yaml_text", "message"), [
        ("name: x\nstart_date: 2026-07-01\nend_date: 2026-07-14\n2026-07-10: 1\nentries: []\n",
         "unknown key datetime.date(2026, 7, 10)"),
        ("name: !!binary aGk=\nstart_date: 2026-07-01\nend_date: 2026-07-14\nentries: []\n", "plan.name"),
        ("name: x\nstart_date: 2026-07-01\nend_date: 2026-07-14\nentries: &e [*e]\n", "recursive"),
    ])
    def test_malformed_yaml_is_invalid_input(self, mocker: Any, yaml_text: str, message: str) -> None:
        auth = mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        result = _invoke(["--json", "plan", "preview", "-", "--input-format", "yaml"], stdin=yaml_text)
        envelope = json.loads(result.stdout)
        assert envelope["error_code"] == "INVALID_INPUT"
        assert message in envelope["error"]
        auth.assert_not_called()


class TestApply:

    def test_yes_applies_and_prints_the_result(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        apply = mocker.patch("garmin_cli.commands.plan.apply_training_plan", return_value=APPLIED)
        result = _invoke(["--json", "plan", "apply", _plan_file(tmp_path), "--yes"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["data"] == [APPLIED]
        apply.assert_called_once_with(PLAN)

    def test_rolled_back_apply_reports_operations_and_exits_1(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch("garmin_cli.commands.plan.apply_training_plan", return_value=ROLLED_BACK)
        result = _invoke(["plan", "apply", _plan_file(tmp_path), "--yes"])
        assert result.exit_code == 1
        assert "compensated" in result.stdout
        assert "SERVER_ERROR" in result.stdout

    def test_json_without_yes_is_refused_before_auth(self, mocker: Any, tmp_path: Path) -> None:
        auth = mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        apply = mocker.patch("garmin_cli.commands.plan.apply_training_plan")
        result = _invoke(["--json", "plan", "apply", _plan_file(tmp_path)])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error_code"] == "INVALID_INPUT"
        assert "--confirm" in envelope["error"]
        auth.assert_not_called()
        apply.assert_not_called()

    def test_stdin_plan_needs_yes_even_at_a_terminal(self, mocker: Any) -> None:
        # A plan piped into a terminal session must not leave the prompt to read its tail.
        mocker.patch("garmin_cli.commands._options.stdin_is_tty", return_value=True)
        auth = mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        read = mocker.patch("garmin_cli.commands.plan.read_workout_input")
        apply = mocker.patch("garmin_cli.commands.plan.apply_training_plan")
        result = _invoke(["plan", "apply", "-"], stdin=json.dumps(PLAN) + "\ny\n")
        assert result.exit_code == 1
        assert "Confirmation required" in result.stderr
        read.assert_not_called()
        auth.assert_not_called()
        apply.assert_not_called()

    def test_stdin_plan_with_yes_applies(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        apply = mocker.patch("garmin_cli.commands.plan.apply_training_plan", return_value=APPLIED)
        result = _invoke(["plan", "apply", "-", "--yes"], stdin=json.dumps(PLAN))
        assert result.exit_code == 0, result.stderr
        apply.assert_called_once_with(PLAN)

    def test_table_shows_restored_schedule_id(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        restored = {**ROLLED_BACK, "operations": [{"action": "restore_source", "schedule_id": 7, "workout_id": 10,
                                                   "date": "2026-07-09", "state": "compensated",
                                                   "restored_schedule_id": 8123}]}
        mocker.patch("garmin_cli.commands.plan.apply_training_plan", return_value=restored)
        result = _invoke(["plan", "apply", _plan_file(tmp_path), "--yes"])
        assert "restored_schedule_id" in result.stdout and "8123" in result.stdout

    @pytest.mark.parametrize(("answer", "applied"), [("y\n", True), ("n\n", False)])
    def test_terminal_prompt(self, mocker: Any, tmp_path: Path, answer: str, applied: bool) -> None:
        mocker.patch("garmin_cli.commands._options.stdin_is_tty", return_value=True)
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        apply = mocker.patch("garmin_cli.commands.plan.apply_training_plan", return_value=APPLIED)
        result = _invoke(["plan", "apply", _plan_file(tmp_path)], stdin=answer)
        assert "Apply plan 'July block' (1 entries, 0 removals)" in result.stderr
        assert apply.called is applied
        assert result.exit_code == (0 if applied else 1)

    def test_stdin_dry_run_needs_no_yes(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        _patch_calendar(mocker)
        apply = mocker.patch("garmin_cli.commands.plan.apply_training_plan")
        result = _invoke(["--json", "plan", "apply", "-", "--dry-run"], stdin=json.dumps(PLAN))
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["data"][0]["operations"][0]["action"] == "keep"
        apply.assert_not_called()

    def test_help_says_stdin_needs_confirm_unless_dry_run(self) -> None:
        assert "unless --dry-run" in _invoke(["plan", "apply", "--help"]).stdout

    def test_dry_run_previews_without_writing_or_confirming(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        _patch_calendar(mocker)
        apply = mocker.patch("garmin_cli.commands.plan.apply_training_plan")
        result = _invoke(["--json", "plan", "apply", _plan_file(tmp_path), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["data"][0]["operations"][0]["action"] == "keep"
        apply.assert_not_called()

    def test_invalid_plan_is_invalid_input(self, mocker: Any, tmp_path: Path) -> None:
        apply = mocker.patch("garmin_cli.commands.plan.apply_training_plan")
        result = _invoke(["--json", "plan", "apply", _plan_file(tmp_path, {**PLAN, "bogus": 1}), "--yes"])
        assert json.loads(result.stdout)["error_code"] == "INVALID_INPUT"
        apply.assert_not_called()


class TestReschedule:

    ARGS = ["plan", "reschedule", "--schedule-id", "42", "--new-date", "2026-07-12", "--expected-date", "2026-07-10"]

    def test_yes_moves_through_the_service(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        moved = {**APPLIED, "operations": [{"action": "move", "state": "verified", "schedule_id": 1001}]}
        move = mocker.patch("garmin_cli.commands.plan.reschedule_schedule", return_value=moved)
        result = _invoke(["--json", *self.ARGS, "--yes"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["data"] == [moved]
        move.assert_called_once_with(42, date(2026, 7, 12), "2026-07-10")

    def test_conflict_exits_1(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.plan.reschedule_schedule",
            return_value={"complete": False, "outcome": "partial", "operations": [], "errors": [],
                          "conflicts": [{"reason": "destination_occupied"}]},
        )
        result = _invoke([*self.ARGS, "--yes"])
        assert result.exit_code == 1
        assert "destination_occupied" in result.stdout

    def test_refused_without_yes_and_bad_id(self, mocker: Any) -> None:
        move = mocker.patch("garmin_cli.commands.plan.reschedule_schedule")
        assert json.loads(_invoke(["--json", *self.ARGS]).stdout)["error_code"] == "INVALID_INPUT"
        bad = [*self.ARGS[:3], "abc", *self.ARGS[4:], "--yes"]
        assert json.loads(_invoke(["--json", *bad]).stdout)["error"] == "--schedule-id must be a positive integer"
        move.assert_not_called()

    def test_interactive_decline_skips_login_and_write(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands._options.stdin_is_tty", return_value=True)
        auth = mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        move = mocker.patch("garmin_cli.commands.plan.reschedule_schedule")
        result = _invoke(self.ARGS, stdin="n\n")
        assert result.exit_code == 1
        assert "Move workout schedule 42 from 2026-07-10 to 2026-07-12?" in result.stderr
        auth.assert_not_called()
        move.assert_not_called()


RECONCILED = {
    "entries": [
        {"planned": {"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": 99, "sport": "running",
                     "duration_min": 45, "name": "Tempo"},
         "actual": {"activity_id": 1, "date": "2026-07-10", "sport": "running"},
         "state": "completed_exact", "match_method": "workout_id", "match_confidence": "exact",
         "data_quality": []},
    ],
    "provenance": {"activities_examined": 1, "detail_requests": 1, "max_activities": 50,
                   "truncated": False, "detail": "summary"},
}


class TestReconcile:

    def test_table_flattens_entries(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        collect = mocker.patch("garmin_cli.commands.plan.collect_reconciliation", return_value=RECONCILED)
        result = _invoke(["plan", "reconcile", "--from", "2026-07-01", "--to", "2026-07-14", "--detail", "targets"])
        assert result.exit_code == 0, result.output
        assert "completed_exact" in result.stdout and "Tempo" in result.stdout
        collect.assert_called_once_with(date(2026, 7, 1), date(2026, 7, 14), "targets", 50)

    def test_json_is_the_full_result(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch("garmin_cli.commands.plan.collect_reconciliation", return_value=RECONCILED)
        result = _invoke(["--json", "plan", "reconcile", "--from", "2026-07-01", "--to", "2026-07-14"])
        envelope = json.loads(result.stdout)
        assert envelope["data"] == [RECONCILED]
        assert envelope["date_range"] == {"from": "2026-07-01", "to": "2026-07-14"}

    def test_defaults_to_the_last_7_days(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch("garmin_cli.date_utils.today", return_value=date(2026, 7, 14))
        collect = mocker.patch("garmin_cli.commands.plan.collect_reconciliation", return_value=RECONCILED)
        assert _invoke(["plan", "reconcile"]).exit_code == 0
        assert collect.call_args.args[:2] == (date(2026, 7, 8), date(2026, 7, 14))

    @pytest.mark.parametrize(("extra", "message"), [
        (["--days", "29"], "cannot exceed 28 days"),
        (["--from", "2026-06-01", "--to", "2026-06-29"], "cannot exceed 28 days"),
        (["--days", "91"], "cannot exceed 28 days"),
        (["--from", "2026-04-01", "--to", "2026-07-01"], "cannot exceed 28 days"),
        (["--days", "7", "--max-activities", "101"], "--max-activities must be between 1 and 100"),
        (["--days", "7", "--max-activities", "0"], "--max-activities must be between 1 and 100"),
    ])
    def test_bounds_are_invalid_input_before_auth(self, mocker: Any, extra: list[str], message: str) -> None:
        auth = mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        result = _invoke(["--json", "plan", "reconcile", *extra])
        envelope = json.loads(result.stdout)
        assert envelope["error_code"] == "INVALID_INPUT"
        assert message in envelope["error"]
        auth.assert_not_called()

    @pytest.mark.parametrize("fmt", ["table", "csv"])
    def test_activity_cap_warns_on_stderr(self, mocker: Any, fmt: str) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        capped = {**RECONCILED, "provenance": {**RECONCILED["provenance"], "truncated": True}}
        mocker.patch("garmin_cli.commands.plan.collect_reconciliation", return_value=capped)
        result = _invoke(["--format", fmt, "plan", "reconcile", "--days", "7"])
        assert result.exit_code == 0, result.output
        assert "--max-activities" in result.stderr and "--max-activities" not in result.stdout

    def test_activity_cap_json_unchanged(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        capped = {**RECONCILED, "provenance": {**RECONCILED["provenance"], "truncated": True}}
        mocker.patch("garmin_cli.commands.plan.collect_reconciliation", return_value=capped)
        result = _invoke(["--json", "plan", "reconcile", "--days", "7"])
        assert result.stderr == ""
        assert json.loads(result.stdout)["data"] == [capped]

    def test_targets_row_shows_comparison_state(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        entry = {**RECONCILED["entries"][0], "target_comparison": {"state": "completed", "targets": [{"kind": "hr"}]}}
        mocker.patch("garmin_cli.commands.plan.collect_reconciliation",
                     return_value={**RECONCILED, "entries": [entry]})
        result = _invoke(["--format", "csv", "plan", "reconcile", "--days", "7", "--detail", "targets"])
        assert result.stdout.splitlines()[1] == "2026-07-10,completed_exact,Tempo,10,1,running,workout_id,completed"

    def test_days_help_states_the_28_day_cap(self) -> None:
        assert "(1-28)" in _invoke(["plan", "reconcile", "--help"]).stdout

    def test_rows_for_unplanned_and_skipped_entries(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        entries = [
            {"planned": None, "actual": {"activity_id": 5, "date": "2026-07-11", "sport": "cycling"},
             "state": "unplanned_activity", "match_method": None, "match_confidence": None, "data_quality": []},
            {"planned": {"date": "2026-07-09", "workout_id": 20, "sport": "running", "name": "Easy"},
             "actual": None, "state": "skipped", "match_method": None, "match_confidence": None, "data_quality": []},
        ]
        mocker.patch("garmin_cli.commands.plan.collect_reconciliation",
                     return_value={"entries": entries, "provenance": {}})
        result = _invoke(["--format", "csv", "plan", "reconcile", "--from", "2026-07-01", "--to", "2026-07-14"])
        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[1:] == [
            "2026-07-11,unplanned_activity,,,5,cycling,,",
            "2026-07-09,skipped,Easy,20,,running,,",
        ]


class TestMcpParity:
    """The CLI prints exactly what the MCP tool returns for the same Garmin state."""

    def test_preview(self, mocker: Any, tmp_path: Path) -> None:
        require_mcp()
        from garmin_cli.mcp_server import create_mcp_server
        from tests.test_mcp_tools.support import _call, _config

        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        _patch_calendar(mocker)
        cli_data = json.loads(_invoke(["--json", "plan", "preview", _plan_file(tmp_path)]).stdout)["data"][0]
        assert cli_data == _call(create_mcp_server(_config()), "training_plan_preview", {"plan": PLAN})

    def test_apply(self, mocker: Any, tmp_path: Path) -> None:
        require_mcp()
        from garmin_cli.mcp_server import create_mcp_server
        from tests.test_mcp_tools.support import _call, _config

        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.training_plan.ensure_authenticated")
        mocker.patch("garmin_cli.commands.plan.apply_training_plan", return_value=ROLLED_BACK)
        mocker.patch("garmin_cli.mcp_tools.training_plan.apply_training_plan", return_value=ROLLED_BACK)
        cli_data = json.loads(_invoke(["--json", "plan", "apply", _plan_file(tmp_path), "--yes"]).stdout)["data"][0]
        assert cli_data == _call(create_mcp_server(_config()), "training_plan_apply", {"plan": PLAN})

    def test_reschedule(self, mocker: Any) -> None:
        require_mcp()
        from garmin_cli.mcp_server import create_mcp_server
        from tests.test_mcp_tools.support import _call, _config

        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.training_plan.ensure_authenticated")
        # The source is gone from its expected date: both refuse with the same conflict.
        mocker.patch("garmin_cli.services.schedule_writes.get_calendar_range", return_value=[])
        cli_out = _invoke(["--json", *TestReschedule.ARGS, "--yes"])
        mcp_data = _call(
            create_mcp_server(_config()), "training_plan_reschedule",
            {"schedule_id": 42, "new_date": "2026-07-12", "expected_date": "2026-07-10"},
        )
        assert json.loads(cli_out.stdout)["data"][0] == mcp_data
        assert mcp_data["conflicts"] == [{"reason": "source_schedule_changed"}]

    def test_reconcile(self, mocker: Any) -> None:
        require_mcp()
        from garmin_cli.mcp_server import create_mcp_server
        from tests.test_mcp_tools.support import _call, _config

        mocker.patch("garmin_cli.commands.plan.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.services.plan_reconcile.today", return_value=date(2026, 7, 20))
        mocker.patch(
            "garmin_cli.services.plan_reconcile.get_calendar_range",
            return_value=[{"date": "2026-07-10", "workoutId": 10, "workoutTypeKey": "running"}],
        )
        activity = {"activityId": 1, "startTimeLocal": "2026-07-10T08:00:00",
                    "activityType": {"typeKey": "running"}, "metadataDTO": {"associatedWorkoutId": 10}}
        mocker.patch("garmin_cli.services.plan_reconcile.list_activities", return_value=[activity])
        mocker.patch("garmin_cli.services.plan_reconcile.get_activity", return_value=activity)
        cli_out = _invoke(["--json", "plan", "reconcile", "--from", "2026-07-01", "--to", "2026-07-14"])
        cli_data = json.loads(cli_out.stdout)["data"][0]
        mcp_data = _call(
            create_mcp_server(_config()), "training_plan_reconcile",
            {"start_date": "2026-07-01", "end_date": "2026-07-14"},
        )
        assert cli_data == mcp_data
        assert cli_data["entries"][0]["state"] == "completed_exact"
