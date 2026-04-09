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
