"""CLI contract tests for the coaching snapshot surface."""

from __future__ import annotations

import json
from typing import Any

from click.testing import CliRunner

from garmin_cli.cli import cli


def test_coach_snapshot_json_emits_shared_service_result(mocker: Any) -> None:
    auth = mocker.patch("garmin_cli.commands.coaching.ensure_authenticated")
    snapshot = {
        "complete": True,
        "aborted": False,
        "as_of": "2026-07-15",
        "recovery": {"signals": []},
        "provenance": {"estimated_requests": 30, "completed_requests": 30, "truncated": False},
    }
    collect = mocker.patch("garmin_cli.commands.coaching.collect_snapshot", return_value=snapshot)

    result = CliRunner(mix_stderr=False).invoke(
        cli,
        ["--json", "coach", "snapshot", "--date", "2026-07-15"],
    )

    assert result.exit_code == 0
    envelope = json.loads(result.output)
    assert envelope["ok"] is True
    assert envelope["command"] == "coach snapshot"
    assert envelope["data"] == [snapshot]
    auth.assert_called_once()
    assert collect.call_args.args[0].isoformat() == "2026-07-15"
    assert collect.call_args.args[-1] == 24


def test_coach_snapshot_table_points_to_json_for_other_sections(mocker: Any) -> None:
    mocker.patch("garmin_cli.commands.coaching.ensure_authenticated")
    mocker.patch(
        "garmin_cli.commands.coaching.collect_snapshot",
        return_value={"recovery": {"signals": [{"signal": "hrv", "state": "normal"}]}},
    )

    result = CliRunner(mix_stderr=False).invoke(cli, ["coach", "snapshot"])

    assert result.exit_code == 0
    assert "hrv" in result.stdout
    assert "Use --json" in result.stdout


def test_coach_snapshot_rejects_csv_before_auth(mocker: Any) -> None:
    auth = mocker.patch("garmin_cli.commands.coaching.ensure_authenticated")

    result = CliRunner(mix_stderr=False).invoke(cli, ["--format", "csv", "coach", "snapshot"])

    assert result.exit_code == 1
    assert "--json" in result.stderr
    auth.assert_not_called()
