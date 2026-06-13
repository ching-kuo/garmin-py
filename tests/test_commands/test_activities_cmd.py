"""CLI integration tests for activity commands using CliRunner."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli


# ---------------------------------------------------------------------------
# activity list command
# ---------------------------------------------------------------------------

class TestActivityListCommand:

    def test_list_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["activity", "list"])
        mock_auth.assert_called_once()

    def test_list_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "list"])
        assert result.exit_code == 0

    def test_list_limit_flag(self, mocker: Any) -> None:
        mock_list = mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[],
        )
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["activity", "list", "--limit", "5"])
        call_kwargs = mock_list.call_args
        assert call_kwargs is not None
        # limit=5 should be passed
        args_str = str(call_kwargs)
        assert "5" in args_str

    def test_list_json_envelope_ok_true(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[{"activityId": 1}],
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[{"id": 1, "name": "Run", "type": "running"}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "list"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_list_count_matches_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[{}, {}],
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[{"id": 1}, {"id": 2}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "list"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 2
        assert len(parsed["data"]) == 2

    def test_list_limit_0_returns_bad_parameter(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "list", "--limit", "0"])
        assert result.exit_code == 1

    def test_list_limit_negative_returns_error(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "list", "--limit", "-1"])
        assert result.exit_code == 1

    def test_list_activity_type_filter(self, mocker: Any) -> None:
        mock_list = mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[],
        )
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["activity", "list", "--type", "running"])
        args_str = str(mock_list.call_args)
        assert "running" in args_str

    def test_list_search_filter(self, mocker: Any) -> None:
        mock_list = mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[],
        )
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["activity", "list", "--search", "marathon"])
        args_str = str(mock_list.call_args)
        assert "marathon" in args_str

    def test_list_auth_failure_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.activities.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "list"])
        assert result.exit_code == 1

    def test_list_auth_failure_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch(
            "garmin_cli.commands.activities.ensure_authenticated",
            side_effect=GarminCliError(error="No creds", error_code="AUTH_MISSING"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "list"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "AUTH_MISSING"

    def test_list_date_option(self, mocker: Any) -> None:
        mock_list = mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[],
        )
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "list", "--date", "2026-03-15"])
        assert result.exit_code == 0
        call_kwargs = mock_list.call_args
        assert call_kwargs.kwargs.get("start_date") == date(2026, 3, 15)
        assert call_kwargs.kwargs.get("end_date") == date(2026, 3, 15)

    def test_list_days_option(self, mocker: Any) -> None:
        mock_list = mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[],
        )
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "list", "--days", "7"])
        assert result.exit_code == 0
        call_kwargs = mock_list.call_args
        assert call_kwargs.kwargs.get("start_date") is not None
        assert call_kwargs.kwargs.get("end_date") is not None

    def test_list_from_to_option(self, mocker: Any) -> None:
        mock_list = mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[],
        )
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, [
            "--json", "activity", "list",
            "--from", "2026-03-01", "--to", "2026-03-10",
        ])
        assert result.exit_code == 0
        call_kwargs = mock_list.call_args
        assert call_kwargs.kwargs.get("start_date") == date(2026, 3, 1)
        assert call_kwargs.kwargs.get("end_date") == date(2026, 3, 10)

    def test_list_date_range_in_json_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.list_activities",
            return_value=[],
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, [
            "--json", "activity", "list", "--date", "2026-03-15",
        ])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["date_range"] is not None
        assert parsed["date_range"]["from"] == "2026-03-15"
        assert parsed["date_range"]["to"] == "2026-03-15"

    def test_list_conflicting_date_options(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, [
            "activity", "list", "--date", "2026-03-15", "--days", "7",
        ])
        assert result.exit_code != 0

    def test_list_from_without_to_returns_error(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, [
            "activity", "list", "--from", "2026-03-01",
        ])
        assert result.exit_code != 0

    def test_list_to_without_from_returns_error(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, [
            "activity", "list", "--to", "2026-03-31",
        ])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# activity get command
# ---------------------------------------------------------------------------

class TestActivityGetCommand:

    def test_get_calls_auth(self, mocker: Any) -> None:
        mock_auth = mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 12345678},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[{"id": 12345678}],
        )
        runner = CliRunner(mix_stderr=False)
        runner.invoke(cli, ["activity", "get", "12345678"])
        mock_auth.assert_called_once()

    def test_get_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 12345678},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[{"id": 12345678}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "12345678"])
        assert result.exit_code == 0

    def test_get_singleton_wrapped_in_list(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 12345678},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[{"id": 12345678, "name": "Run"}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "12345678"])
        parsed = json.loads(result.output)
        assert parsed["count"] == 1
        assert isinstance(parsed["data"], list)

    def test_get_not_found_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "get", "99999999"])
        assert result.exit_code == 1

    def test_get_not_found_json_error_envelope(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "99999999"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "NOT_FOUND"

    # -- detail flag tests --

    def test_get_detail_table_extended_columns(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 12345678},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_detail",
            return_value=[{
                "id": 12345678, "date": "2026-03-11T07:30:00", "name": "Run",
                "type": "running", "distance_km": 10.0, "duration_min": 60.0,
                "avg_hr": 155, "max_hr": 178, "calories": 650,
                "elevation_gain_m": 120.0, "elevation_loss_m": 100.0,
                "avg_speed_kmh": 10.0, "max_speed_kmh": 14.0,
                "avg_cadence_spm": 180, "avg_cadence_rpm": None,
                "avg_power_w": None, "max_power_w": None, "norm_power_w": None,
                "tss": None, "intensity_factor": None,
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "get", "12345678", "--detail"])
        assert result.exit_code == 0
        assert "max_hr" in result.output or "178" in result.output

    def test_get_detail_json_extended_fields(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 12345678},
        )
        detail_row = {
            "id": 12345678, "date": "2026-03-11T07:30:00", "name": "Run",
            "type": "running", "distance_km": 10.0, "duration_min": 60.0,
            "avg_hr": 155, "max_hr": 178, "calories": 650,
            "elevation_gain_m": 120.0, "elevation_loss_m": 100.0,
            "avg_speed_kmh": 10.0, "max_speed_kmh": 14.0,
            "avg_cadence_spm": 180, "avg_cadence_rpm": None,
            "avg_power_w": None, "max_power_w": None, "norm_power_w": None,
            "tss": None, "intensity_factor": None,
        }
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_detail",
            return_value=[detail_row],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "12345678", "--detail"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert parsed["data"][0]["max_hr"] == 178
        assert parsed["data"][0]["calories"] == 650
        assert "elevation_gain_m" in parsed["data"][0]

    def test_get_detail_csv_extended_fields(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 12345678},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_detail",
            return_value=[{
                "id": 12345678, "date": "2026-03-11T07:30:00", "name": "Run",
                "type": "running", "distance_km": 10.0, "duration_min": 60.0,
                "avg_hr": 155, "max_hr": 178, "calories": 650,
                "elevation_gain_m": 120.0, "elevation_loss_m": 100.0,
                "avg_speed_kmh": 10.0, "max_speed_kmh": 14.0,
                "avg_cadence_spm": 180, "avg_cadence_rpm": None,
                "avg_power_w": None, "max_power_w": None, "norm_power_w": None,
                "tss": None, "intensity_factor": None,
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--format", "csv", "activity", "get", "12345678", "--detail"])
        assert result.exit_code == 0
        assert "max_hr" in result.output
        assert "calories" in result.output

    def test_get_default_no_detail_unchanged(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 12345678},
        )
        mock_summary = mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_summary",
            return_value=[{"id": 12345678, "name": "Run", "type": "running"}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "12345678"])
        assert result.exit_code == 0
        mock_summary.assert_called_once()

    def test_get_detail_short_flag(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 12345678},
        )
        mock_detail = mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_detail",
            return_value=[{
                "id": 12345678, "date": "2026-03-11", "name": "Run",
                "type": "running", "distance_km": 10.0, "duration_min": 60.0,
                "avg_hr": 155, "max_hr": 178, "calories": 650,
                "elevation_gain_m": None, "elevation_loss_m": None,
                "avg_speed_kmh": None, "max_speed_kmh": None,
                "avg_cadence_spm": None, "avg_cadence_rpm": None,
                "avg_power_w": None, "max_power_w": None, "norm_power_w": None,
                "tss": None, "intensity_factor": None,
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "12345678", "-d"])
        assert result.exit_code == 0
        mock_detail.assert_called_once()

    def test_get_detail_multisport_parent_json(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 100,
                "activityType": {"typeKey": "multi_sport"},
                "isMultiSportParent": True,
                "childIds": [101, 102],
            },
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_detail",
            return_value=[{
                "id": 100, "date": "2026-04-06T06:00:00", "name": "Tri",
                "type": "multi_sport", "distance_km": None, "duration_min": None,
                "avg_hr": None, "max_hr": None, "calories": None,
                "elevation_gain_m": None, "elevation_loss_m": None,
                "avg_speed_kmh": None, "max_speed_kmh": None,
                "avg_cadence_spm": None, "avg_cadence_rpm": None,
                "avg_power_w": None, "max_power_w": None, "norm_power_w": None,
                "tss": None, "intensity_factor": None,
            }],
        )
        mocker.patch(
            "garmin_cli.commands.activities.get_multisport_children",
            return_value=[
                {"activityId": 101, "activityName": "Swim", "activityType": {"typeKey": "swimming"},
                 "distance": 1500.0, "duration": 1800.0, "averageHR": 145, "averageSpeed": 0.833, "calories": 350},
                {"activityId": 102, "activityName": "Bike", "activityType": {"typeKey": "cycling"},
                 "distance": 40000.0, "duration": 4200.0, "averageHR": 155, "averageSpeed": 9.524, "calories": 900},
            ],
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_multisport_children",
            return_value=[
                {"id": 101, "sport": "swimming", "name": "Swim", "distance_km": 1.5, "duration_min": 30.0, "avg_hr": 145, "avg_pace": "20:00", "calories": 350},
                {"id": 102, "sport": "cycling", "name": "Bike", "distance_km": 40.0, "duration_min": 70.0, "avg_hr": 155, "avg_pace": None, "calories": 900},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "100", "--detail"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert "max_hr" in parsed["data"][0]
        assert "children" in parsed
        assert len(parsed["children"]) == 2

    def test_get_detail_multisport_parent_table(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 100,
                "activityType": {"typeKey": "multi_sport"},
                "isMultiSportParent": True,
                "childIds": [101],
            },
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_detail",
            return_value=[{
                "id": 100, "date": "2026-04-06T06:00:00", "name": "Tri",
                "type": "multi_sport", "distance_km": None, "duration_min": None,
                "avg_hr": None, "max_hr": None, "calories": None,
                "elevation_gain_m": None, "elevation_loss_m": None,
                "avg_speed_kmh": None, "max_speed_kmh": None,
                "avg_cadence_spm": None, "avg_cadence_rpm": None,
                "avg_power_w": None, "max_power_w": None, "norm_power_w": None,
                "tss": None, "intensity_factor": None,
            }],
        )
        mocker.patch(
            "garmin_cli.commands.activities.get_multisport_children",
            return_value=[{"activityId": 101, "activityName": "Run", "activityType": {"typeKey": "running"}}],
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_multisport_children",
            return_value=[{"id": 101, "sport": "running", "name": "Run", "distance_km": 10.0, "duration_min": 50.0, "avg_hr": 165, "avg_pace": "5:00", "calories": 600}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "get", "100", "--detail"])
        assert result.exit_code == 0
        assert "Child activities:" in result.output

    def test_get_detail_multisport_csv_includes_parent(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 100,
                "activityType": {"typeKey": "multi_sport"},
                "isMultiSportParent": True,
                "childIds": [101],
            },
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_detail",
            return_value=[{
                "id": 100, "date": "2026-04-06T06:00:00", "name": "Tri",
                "type": "multi_sport", "distance_km": None, "duration_min": None,
                "avg_hr": None, "max_hr": None, "calories": 1800,
                "elevation_gain_m": None, "elevation_loss_m": None,
                "avg_speed_kmh": None, "max_speed_kmh": None,
                "avg_cadence_spm": None, "avg_cadence_rpm": None,
                "avg_power_w": None, "max_power_w": None, "norm_power_w": None,
                "tss": None, "intensity_factor": None,
            }],
        )
        mocker.patch(
            "garmin_cli.commands.activities.get_multisport_children",
            return_value=[{"activityId": 101, "activityName": "Run", "activityType": {"typeKey": "running"}}],
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_multisport_children",
            return_value=[{"id": 101, "sport": "running", "name": "Run", "distance_km": 10.0, "duration_min": 50.0, "avg_hr": 165, "avg_pace": "5:00", "calories": 600}],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--format", "csv", "activity", "get", "100", "--detail"])
        assert result.exit_code == 0
        assert "100" in result.output
        assert "1800" in result.output

    def test_get_detail_all_null_extended_renders(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 12345678},
        )
        mocker.patch(
            "garmin_cli.commands.activities.serialize_activity_detail",
            return_value=[{
                "id": 12345678, "date": "2026-03-11", "name": "Walk",
                "type": "walking", "distance_km": 2.0, "duration_min": 30.0,
                "avg_hr": None, "max_hr": None, "calories": None,
                "elevation_gain_m": None, "elevation_loss_m": None,
                "avg_speed_kmh": None, "max_speed_kmh": None,
                "avg_cadence_spm": None, "avg_cadence_rpm": None,
                "avg_power_w": None, "max_power_w": None, "norm_power_w": None,
                "tss": None, "intensity_factor": None,
            }],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "get", "12345678", "--detail"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Sport-aware CLI behavior (U5)
# ---------------------------------------------------------------------------


class TestSportAwareActivityGet:
    """Verify CLI uses sport-aware columns for table and union for CSV."""

    def test_running_table_omits_cycling_power_columns(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 1, "activityType": {"typeKey": "running"},
                "averageRunningCadenceInStepsPerMinute": 180.0,
                "avgGroundContactTime": 240,
            },
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "get", "1", "--detail"])
        assert result.exit_code == 0
        # Cycling power headers should not appear in a running activity table
        assert "norm_power_w" not in result.output
        assert "intensity_factor" not in result.output
        # Running dynamics column header should appear
        assert "avg_ground_contact_time" in result.output

    def test_cycling_table_omits_running_dynamics_columns(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 2, "activityType": {"typeKey": "cycling"},
                "averagePower": 220.0, "normPower": 240.0,
            },
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "get", "2", "--detail"])
        assert result.exit_code == 0
        # Cycling power headers appear
        assert "avg_power_w" in result.output
        assert "norm_power_w" in result.output
        # Running dynamics columns should not appear in cycling table
        assert "avg_ground_contact_time" not in result.output
        assert "avg_stride_length" not in result.output

    def test_swim_table_omits_cycling_and_running_columns(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 3, "activityType": {"typeKey": "lap_swimming"},
                "avgSwolf": 38, "strokes": 720,
            },
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "get", "3", "--detail"])
        assert result.exit_code == 0
        assert "swolf" in result.output
        assert "total_strokes" in result.output
        assert "avg_power_w" not in result.output
        assert "avg_ground_contact_time" not in result.output

    def test_csv_uses_stable_union_header(self, mocker: Any) -> None:
        from garmin_cli.serializers import COLUMNS_ACTIVITY_DETAIL

        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 4, "activityType": {"typeKey": "cycling"},
                "averagePower": 220.0,
            },
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--format", "csv", "activity", "get", "4", "--detail"])
        assert result.exit_code == 0
        first_line = result.output.splitlines()[0]
        # Header must contain every union column, in stable order
        for col in COLUMNS_ACTIVITY_DETAIL:
            assert col in first_line

    def test_csv_legacy_columns_keep_legacy_positions(self, mocker: Any) -> None:
        legacy_prefix = (
            "id", "date", "name", "type", "distance_km", "duration_min", "avg_hr",
            "max_hr", "calories", "elevation_gain_m", "elevation_loss_m",
            "avg_speed_kmh", "max_speed_kmh",
            "avg_cadence_spm", "avg_cadence_rpm",
            "avg_power_w", "max_power_w", "norm_power_w",
            "tss", "intensity_factor",
        )
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 5, "activityType": {"typeKey": "cycling"},
            },
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--format", "csv", "activity", "get", "5", "--detail"])
        assert result.exit_code == 0
        header_columns = result.output.splitlines()[0].split(",")
        # legacy keys must occupy the first 20 positions in their legacy order
        assert tuple(header_columns[: len(legacy_prefix)]) == legacy_prefix

    def test_json_returns_union_keys_with_nulls_for_other_sports(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 6, "activityType": {"typeKey": "running"},
                "averageRunningCadenceInStepsPerMinute": 175.0,
                "avgGroundContactTime": 230,
            },
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "6", "--detail"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        row = parsed["data"][0]
        # populated running keys
        assert row["avg_cadence_spm"] == pytest.approx(175.0)
        assert row["avg_ground_contact_time"] == 230
        # cycling/swim keys present but null
        assert row["norm_power_w"] is None
        assert row["swolf"] is None


# ---------------------------------------------------------------------------
# Capability manifest in CLI output (U11)
# ---------------------------------------------------------------------------


class TestCapabilityManifestInCli:

    def test_json_envelope_includes_unavailable_for_running(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "running"}},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "1", "--detail"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "unavailable" in parsed
        # cycling and swim metrics tagged as not applicable to running
        reasons = {entry["field"]: entry["reason"] for entry in parsed["unavailable"]}
        assert reasons.get("avg_power_w") == "not_applicable_to_sport"
        assert reasons.get("swolf") == "not_applicable_to_sport"

    def test_json_envelope_omits_unavailable_when_empty(self, mocker: Any) -> None:
        # Hypothetical: activity has all registered metrics populated for its sport.
        # In practice some will always be absent; assert at least that the field
        # only appears when there is content.
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "running"}},
        )
        runner = CliRunner(mix_stderr=False)
        # without --detail, manifest is not computed
        result = runner.invoke(cli, ["--json", "activity", "get", "1"])
        parsed = json.loads(result.output)
        assert "unavailable" not in parsed

    def test_table_renders_footnote_when_manifest_non_empty(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "lap_swimming"}},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "get", "1", "--detail"])
        assert result.exit_code == 0
        # footnote is present, with counts only (not full per-field list)
        assert "Note:" in result.output
        assert "not applicable" in result.output

    def test_csv_does_not_emit_manifest(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "running"}},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--format", "csv", "activity", "get", "1", "--detail"])
        assert result.exit_code == 0
        # CSV stays a flat tabular format — no manifest text
        assert "not_applicable_to_sport" not in result.output
        assert "Note:" not in result.output

    def test_summary_only_does_not_emit_manifest(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "running"}},
        )
        runner = CliRunner(mix_stderr=False)
        # No --detail flag → no manifest in JSON
        result = runner.invoke(cli, ["--json", "activity", "get", "1"])
        parsed = json.loads(result.output)
        assert "unavailable" not in parsed
        # No --detail flag → no footnote in table
        result = runner.invoke(cli, ["activity", "get", "1"])
        assert "Note:" not in result.output

    def test_multisport_envelope_unions_child_manifests_with_leg_index(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 100,
                "activityType": {"typeKey": "multi_sport"},
                "isMultiSportParent": True,
                "childIds": [101, 102, 103],
            },
        )
        mocker.patch(
            "garmin_cli.commands.activities.get_multisport_children",
            return_value=[
                {"activityId": 101, "activityType": {"typeKey": "open_water_swimming"}, "averageHR": 145},
                {"activityId": 102, "activityType": {"typeKey": "cycling"}, "averagePower": 200},
                {"activityId": 103, "activityType": {"typeKey": "running"}, "averageRunningCadenceInStepsPerMinute": 175},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "100", "--detail"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "unavailable" in parsed
        # entries from all three legs; leg_index distinguishes them
        leg_indices = {e.get("leg_index") for e in parsed["unavailable"]}
        assert 0 in leg_indices
        assert 1 in leg_indices
        assert 2 in leg_indices


# ---------------------------------------------------------------------------
# activity laps command (U8)
# ---------------------------------------------------------------------------


class TestActivityLapsCommand:

    def test_cycling_laps_invokes_raw_url_splits(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "cycling"}},
        )
        splits_mock = mocker.patch(
            "garmin_cli.commands.activities.get_activity_splits",
            return_value={"lapDTOs": [
                {"duration": 600, "distance": 5000, "averageHR": 145, "averagePower": 220},
                {"duration": 540, "distance": 4500, "averageHR": 152, "averagePower": 230},
            ]},
        )
        typed_splits_mock = mocker.patch(
            "garmin_cli.commands.activities.get_activity_typed_splits",
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "laps", "1"])
        assert result.exit_code == 0
        splits_mock.assert_called_once_with("1")
        typed_splits_mock.assert_not_called()
        parsed = json.loads(result.output)
        assert parsed["count"] == 2
        assert parsed["data"][0]["lap_index"] == 1

    def test_lap_swim_invokes_typed_splits(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "lap_swimming"}},
        )
        splits_mock = mocker.patch(
            "garmin_cli.commands.activities.get_activity_splits",
        )
        typed_splits_mock = mocker.patch(
            "garmin_cli.commands.activities.get_activity_typed_splits",
            return_value={"lengthDTOs": [
                {"duration": 25.0, "distance": 25.0, "swolf": 38, "swimStroke": "FREESTYLE"},
            ]},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "laps", "1"])
        assert result.exit_code == 0
        typed_splits_mock.assert_called_once_with("1")
        splits_mock.assert_not_called()
        parsed = json.loads(result.output)
        assert parsed["data"][0]["swolf"] == 38
        assert parsed["data"][0]["stroke_type"] == "FREESTYLE"

    def test_open_water_swim_uses_raw_splits_not_typed(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "open_water_swimming"}},
        )
        splits_mock = mocker.patch(
            "garmin_cli.commands.activities.get_activity_splits",
            return_value={"lapDTOs": [{"duration": 600, "distance": 1000}]},
        )
        typed_splits_mock = mocker.patch(
            "garmin_cli.commands.activities.get_activity_typed_splits",
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "laps", "1"])
        assert result.exit_code == 0
        splits_mock.assert_called_once()
        typed_splits_mock.assert_not_called()

    def test_invalid_id_returns_exit_code_1(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "laps", "abc"])
        assert result.exit_code == 1

    def test_get_with_laps_flag_includes_laps_in_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "cycling"}, "averagePower": 200},
        )
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_splits",
            return_value={"lapDTOs": [{"duration": 600, "distance": 5000, "averageHR": 145}]},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "1", "--detail", "--laps"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "laps" in parsed
        assert len(parsed["laps"]) == 1
        assert parsed["data"][0]["avg_power_w"] == 200

    def test_multisport_parent_laps_fan_out_with_leg_index(self, mocker: Any) -> None:
        """Multisport activity laps fetches each child and stamps leg_index."""
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={
                "activityId": 100,
                "activityType": {"typeKey": "multi_sport"},
                "isMultiSportParent": True,
                "childIds": [101, 102, 103],
            },
        )
        mocker.patch(
            "garmin_cli.commands.activities.get_multisport_children",
            return_value=[
                {"activityId": 101, "activityType": {"typeKey": "open_water_swimming"}},
                {"activityId": 102, "activityType": {"typeKey": "cycling"}},
                {"activityId": 103, "activityType": {"typeKey": "running"}},
            ],
        )
        # OWS and cycling and running all use raw splits (only lap_swimming uses typed)
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_splits",
            side_effect=[
                {"lapDTOs": [{"duration": 600, "distance": 1000, "averageHR": 140}]},  # OWS
                {"lapDTOs": [{"duration": 1200, "distance": 8000, "averagePower": 220}]},  # bike
                {"lapDTOs": [{"duration": 900, "distance": 3000, "avgGroundContactTime": 235}]},  # run
            ],
        )
        mocker.patch("garmin_cli.commands.activities.get_activity_typed_splits")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "laps", "100"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 3
        leg_indices = {row["leg_index"] for row in parsed["data"]}
        assert leg_indices == {0, 1, 2}

    def test_get_without_laps_flag_omits_laps(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity",
            return_value={"activityId": 1, "activityType": {"typeKey": "cycling"}},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "get", "1", "--detail"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "laps" not in parsed


# ---------------------------------------------------------------------------
# activity zones command (U10)
# ---------------------------------------------------------------------------


class TestActivityZonesCommand:

    def test_zones_returns_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_hr_in_timezones",
            return_value=[
                {"zoneNumber": 1, "zoneLowBoundary": 90, "zoneHighBoundary": 109, "secsInZone": 600},
                {"zoneNumber": 2, "zoneLowBoundary": 110, "zoneHighBoundary": 129, "secsInZone": 1200},
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "zones", "1"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["count"] == 2
        assert parsed["data"][0]["zone"] == 1
        assert parsed["data"][0]["minutes_in_zone"] == 10.0

    def test_zones_table_renders(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_hr_in_timezones",
            return_value=[
                {"zoneNumber": z, "secsInZone": 60 * z, "zoneLowBoundary": 100 + z, "zoneHighBoundary": 110 + z}
                for z in range(1, 6)
            ],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "zones", "1"])
        assert result.exit_code == 0
        # five zones rendered
        assert "zone" in result.output.lower() or "minutes_in_zone" in result.output

    def test_zones_empty_data_renders_no_data(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_hr_in_timezones",
            return_value=[],
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "zones", "1"])
        assert result.exit_code == 0

    def test_zones_invalid_id_exits_1(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "zones", "abc"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# activity weather command
# ---------------------------------------------------------------------------

class TestActivityWeatherCommand:

    def test_weather_exit_code_0(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_weather",
            return_value={"temperature": 12.5},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "weather", "12345678"])
        assert result.exit_code == 0

    def test_weather_json_envelope(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_weather",
            return_value={"temperature": 12.5, "windSpeed": 10.0},
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "weather", "12345678"])
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_weather_not_found_exit_1(self, mocker: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.get_activity_weather",
            side_effect=GarminCliError(error="Not found", error_code="NOT_FOUND"),
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "weather", "99999999"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# activity download / upload / delete commands
# ---------------------------------------------------------------------------

class TestActivityDownloadCommand:

    def test_download_writes_file_and_reports_envelope(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch("garmin_cli.commands.activities.download_activity", return_value=b"FITBYTES")
        out = tmp_path / "ride.zip"
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "activity", "download", "12345", "--output", str(out)]
        )
        assert result.exit_code == 0
        assert out.read_bytes() == b"FITBYTES"
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is True
        row = envelope["data"][0]
        assert row["id"] == "12345"
        assert row["format"] == "original"
        assert row["path"] == str(out)
        assert row["size_bytes"] == len(b"FITBYTES")

    def test_download_refuses_overwrite_without_force(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        dl = mocker.patch("garmin_cli.commands.activities.download_activity", return_value=b"X")
        existing = tmp_path / "exists.zip"
        existing.write_bytes(b"OLD")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--json", "activity", "download", "1", "--output", str(existing)]
        )
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is False
        assert envelope["error_code"] == "INVALID_INPUT"
        dl.assert_not_called()
        assert existing.read_bytes() == b"OLD"

    def test_download_force_overwrites(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch("garmin_cli.commands.activities.download_activity", return_value=b"NEW")
        existing = tmp_path / "exists.zip"
        existing.write_bytes(b"OLD")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["activity", "download", "1", "--output", str(existing), "--force"]
        )
        assert result.exit_code == 0
        assert existing.read_bytes() == b"NEW"

    def test_download_default_filename(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch("garmin_cli.commands.activities.download_activity", return_value=b"D")
        runner = CliRunner(mix_stderr=False)
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["--json", "activity", "download", "777", "--fmt", "gpx"])
            assert result.exit_code == 0
            envelope = json.loads(result.stdout)
            assert envelope["data"][0]["path"].endswith("activity_777.gpx")

    def test_download_rejects_unknown_format_at_parse_time(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "download", "1", "--fmt", "pdf"])
        assert result.exit_code != 0


class TestActivityUploadCommand:

    def test_upload_reports_new_activity_id(self, mocker: Any, tmp_path: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        mocker.patch(
            "garmin_cli.commands.activities.upload_activity",
            return_value={"detailedImportResult": {"successes": [{"internalId": 555}]}},
        )
        f = tmp_path / "run.fit"
        f.write_bytes(b"FIT")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "upload", str(f)])
        assert result.exit_code == 0
        row = json.loads(result.stdout)["data"][0]
        assert row["activity_id"] == 555
        assert row["status"] == "uploaded"

    def test_upload_missing_file_errors(self, mocker: Any, tmp_path: Any) -> None:
        from garmin_cli.exceptions import GarminCliError

        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        up = mocker.patch("garmin_cli.commands.activities.upload_activity")
        up.side_effect = GarminCliError(error="File not found", error_code="INVALID_INPUT")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "upload", str(tmp_path / "nope.fit")])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_code"] == "INVALID_INPUT"


class TestActivityDeleteCommand:

    def test_delete_with_confirm_flag(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        dele = mocker.patch("garmin_cli.commands.activities.delete_activity")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["--json", "activity", "delete", "12345", "--confirm"])
        assert result.exit_code == 0
        row = json.loads(result.stdout)["data"][0]
        assert row == {"id": "12345", "status": "deleted"}
        dele.assert_called_once_with("12345")

    def test_delete_aborts_when_declined(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        dele = mocker.patch("garmin_cli.commands.activities.delete_activity")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "delete", "12345"], input="n\n")
        assert result.exit_code != 0
        dele.assert_not_called()

    def test_delete_proceeds_when_confirmed_interactively(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.commands.activities.ensure_authenticated")
        dele = mocker.patch("garmin_cli.commands.activities.delete_activity")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["activity", "delete", "12345"], input="y\n")
        assert result.exit_code == 0
        dele.assert_called_once_with("12345")
