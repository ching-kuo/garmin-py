"""Tests for garmin_cli.input_reader.read_workout_input."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.input_reader import read_workout_input
from garmin_cli.exceptions import GarminCliError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_WORKOUT: dict = {
    "name": "Morning Run",
    "sport": "running",
    "steps": [
        {"type": "interval", "duration": {"type": "time", "value": 300}}
    ],
}

_VALID_JSON: str = json.dumps(_VALID_WORKOUT)

_VALID_YAML: str = """\
name: Morning Run
sport: running
steps:
  - type: interval
    duration:
      type: time
      value: 300
"""


# ---------------------------------------------------------------------------
# TestReadWorkoutInput
# ---------------------------------------------------------------------------

class TestReadWorkoutInput:

    def test_reads_json_file(self, tmp_path: Any) -> None:
        f = tmp_path / "workout.json"
        f.write_text(_VALID_JSON)
        result = read_workout_input(file_path=str(f))
        assert result["name"] == "Morning Run"

    def test_reads_yaml_file(self, tmp_path: Any) -> None:
        f = tmp_path / "workout.yaml"
        f.write_text(_VALID_YAML)
        result = read_workout_input(file_path=str(f))
        assert result["name"] == "Morning Run"

    def test_detects_yaml_by_yml_extension(self, tmp_path: Any) -> None:
        f = tmp_path / "workout.yml"
        f.write_text(_VALID_YAML)
        result = read_workout_input(file_path=str(f))
        assert result["sport"] == "running"

    def test_input_format_overrides_extension(self, tmp_path: Any) -> None:
        # .json extension but content is YAML with format override
        f = tmp_path / "workout.json"
        f.write_text(_VALID_YAML)
        result = read_workout_input(file_path=str(f), input_format="yaml")
        assert result["name"] == "Morning Run"

    def test_stdin_defaults_to_json(self, mocker: Any) -> None:
        mock_stream = MagicMock()
        mock_stream.read.return_value = _VALID_JSON
        mocker.patch("garmin_cli.input_reader.click.get_text_stream", return_value=mock_stream)
        result = read_workout_input(use_stdin=True)
        assert result["name"] == "Morning Run"

    def test_stdin_yaml_with_format_flag(self, mocker: Any) -> None:
        mock_stream = MagicMock()
        mock_stream.read.return_value = _VALID_YAML
        mocker.patch("garmin_cli.input_reader.click.get_text_stream", return_value=mock_stream)
        result = read_workout_input(use_stdin=True, input_format="yaml")
        assert result["sport"] == "running"

    def test_invalid_json_raises_garmin_cli_error(self, tmp_path: Any) -> None:
        f = tmp_path / "bad.json"
        f.write_text("{ not valid json }")
        with pytest.raises(GarminCliError):
            read_workout_input(file_path=str(f))

    def test_invalid_yaml_raises_garmin_cli_error(self, tmp_path: Any) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text(":\n  : :\n  invalid: yaml: content\n  ]")
        with pytest.raises(GarminCliError):
            read_workout_input(file_path=str(f))

    def test_missing_file_raises_garmin_cli_error(self) -> None:
        with pytest.raises(GarminCliError):
            read_workout_input(file_path="/nonexistent/path/workout.json")

    def test_yaml_not_installed_raises_garmin_cli_error(self, tmp_path: Any, mocker: Any) -> None:
        f = tmp_path / "workout.yaml"
        f.write_text(_VALID_YAML)
        mocker.patch("garmin_cli.input_reader.yaml", None)
        with pytest.raises(GarminCliError):
            read_workout_input(file_path=str(f))

    def test_file_path_none_stdin_true_reads_stdin(self, mocker: Any) -> None:
        mock_stream = MagicMock()
        mock_stream.read.return_value = _VALID_JSON
        mocker.patch("garmin_cli.input_reader.click.get_text_stream", return_value=mock_stream)
        result = read_workout_input(file_path=None, use_stdin=True)
        assert isinstance(result, dict)

    def test_uses_safe_load_not_load(self, tmp_path: Any, mocker: Any) -> None:
        f = tmp_path / "workout.yaml"
        f.write_text(_VALID_YAML)
        mock_yaml = MagicMock()
        mock_yaml.safe_load.return_value = _VALID_WORKOUT
        mocker.patch("garmin_cli.input_reader.yaml", mock_yaml)
        read_workout_input(file_path=str(f))
        mock_yaml.safe_load.assert_called_once()
        mock_yaml.load.assert_not_called()
