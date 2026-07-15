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
    assert json.loads(result.output) == snapshot
    auth.assert_called_once()
    assert collect.call_args.args[0].isoformat() == "2026-07-15"
    assert collect.call_args.args[-1] == 30
