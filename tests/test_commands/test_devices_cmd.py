"""CLI integration tests for device commands using CliRunner."""
from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli


# ---------------------------------------------------------------------------
# device list command
# ---------------------------------------------------------------------------

class TestDeviceListCommand:

    def test_device_group_registered_in_help(self) -> None:
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--help"])
        assert "device" in result.output

    def test_device_list_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.devices.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.devices.get_devices",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.devices.serialize_device",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["device", "list"])
        mock_auth.assert_called_once()

    def test_device_list_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.devices.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.devices.get_devices",
            return_value=[{"deviceId": "abc123"}],
        )
        mocker.patch(
            "garmin_cli.commands.devices.serialize_device",
            return_value=[{
                "device_id": "abc123",
                "display_name": "Forerunner 965",
                "device_type": "GPS_WATCH",
                "last_sync_time": "2026-03-11T09:00:00",
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "device", "list"])
        assert result.exit_code == 0

    def test_device_list_json_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.devices.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.devices.get_devices",
            return_value=[{"deviceId": "abc123"}],
        )
        mocker.patch(
            "garmin_cli.commands.devices.serialize_device",
            return_value=[{
                "device_id": "abc123",
                "display_name": "Forerunner 965",
                "device_type": "GPS_WATCH",
                "last_sync_time": "2026-03-11T09:00:00",
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "device", "list"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_device_list_count_matches_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.devices.ensure_authenticated")
        mocker.patch("garmin_cli.commands.devices.get_devices", return_value=[{}, {}])
        mocker.patch(
            "garmin_cli.commands.devices.serialize_device",
            return_value=[
                {"device_id": "a", "display_name": "Watch A", "device_type": "GPS_WATCH", "last_sync_time": None},
                {"device_id": "b", "display_name": "Watch B", "device_type": "GPS_WATCH", "last_sync_time": None},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "device", "list"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 2
        assert len(parsed["data"]) == 2

    def test_device_list_empty_returns_exit_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.devices.ensure_authenticated")
        mocker.patch("garmin_cli.commands.devices.get_devices", return_value=[])
        mocker.patch("garmin_cli.commands.devices.serialize_device", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "device", "list"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 0
        assert parsed["data"] == []

    def test_device_list_auth_failure_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.devices.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["device", "list"])
        assert result.exit_code == 1

    def test_device_list_auth_failure_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.devices.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "device", "list"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_device_list_table_output_not_json(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.devices.ensure_authenticated")
        mocker.patch("garmin_cli.commands.devices.get_devices", return_value=[{}])
        mocker.patch(
            "garmin_cli.commands.devices.serialize_device",
            return_value=[{
                "device_id": "abc123",
                "display_name": "Forerunner 965",
                "device_type": "GPS_WATCH",
                "last_sync_time": "2026-03-11T09:00:00",
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["device", "list"])
        assert result.exit_code == 0
        try:
            json.loads(result.output)
            is_json = True
        except (json.JSONDecodeError, ValueError):
            is_json = False
        assert not is_json

    def test_device_list_no_date_range_in_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.devices.ensure_authenticated")
        mocker.patch("garmin_cli.commands.devices.get_devices", return_value=[])
        mocker.patch("garmin_cli.commands.devices.serialize_device", return_value=[])
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "device", "list"])
        parsed = json.loads(result.output)
        assert parsed.get("date_range") is None
