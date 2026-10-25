"""Tests for garmin_cli.input_reader.read_workout_input."""
from __future__ import annotations

import io
import json
import sys
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


def _patch_stdin(mocker: Any, payload: bytes, encoding: str = "utf-8") -> None:
    """Replace sys.stdin with a real text stream over *payload* (``encoding`` mimics the locale)."""
    mocker.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload), encoding=encoding))


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
        _patch_stdin(mocker, _VALID_JSON.encode("utf-8"))
        result = read_workout_input(use_stdin=True)
        assert result["name"] == "Morning Run"

    def test_stdin_yaml_with_format_flag(self, mocker: Any) -> None:
        _patch_stdin(mocker, _VALID_YAML.encode("utf-8"))
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

    def test_unreadable_path_raises_invalid_input(self, tmp_path: Any) -> None:
        with pytest.raises(GarminCliError) as exc:
            read_workout_input(file_path=str(tmp_path))
        assert exc.value.error_code == "INVALID_INPUT"

    def test_file_and_stdin_together_raises_invalid_input(self, tmp_path: Any, mocker: Any) -> None:
        f = tmp_path / "workout.json"
        f.write_text(_VALID_JSON)
        _patch_stdin(mocker, _VALID_JSON.encode("utf-8"))
        with pytest.raises(GarminCliError) as exc:
            read_workout_input(file_path=str(f), use_stdin=True)
        assert exc.value.error_code == "INVALID_INPUT"

    def test_stdin_decodes_utf8_regardless_of_locale(self, mocker: Any) -> None:
        _patch_stdin(mocker, json.dumps({"name": "Läufe"}, ensure_ascii=False).encode("utf-8"), encoding="cp1252")
        result = read_workout_input(use_stdin=True)
        assert result["name"] == "Läufe"

    def test_utf8_bom_is_accepted(self, tmp_path: Any, mocker: Any) -> None:
        payload = b"\xef\xbb\xbf" + _VALID_JSON.encode("utf-8")
        f = tmp_path / "bom.json"
        f.write_bytes(payload)
        assert read_workout_input(file_path=str(f)) == _VALID_WORKOUT
        _patch_stdin(mocker, payload)
        assert read_workout_input(use_stdin=True) == _VALID_WORKOUT

    def test_file_invalid_utf8_raises_invalid_input(self, tmp_path: Any) -> None:
        f = tmp_path / "bad.json"
        f.write_bytes(b'{"name": "\xff"}')
        with pytest.raises(GarminCliError) as exc:
            read_workout_input(file_path=str(f))
        assert exc.value.error_code == "INVALID_INPUT"

    def test_closed_stdin_raises_invalid_input(self, mocker: Any) -> None:
        mocker.patch.object(sys, "stdin", None)
        with pytest.raises(GarminCliError) as exc:
            read_workout_input(use_stdin=True)
        assert exc.value.error_code == "INVALID_INPUT"

    def test_stdin_invalid_utf8_raises_garmin_cli_error(self, mocker: Any) -> None:
        _patch_stdin(mocker, b'{"name": "\xff"}')
        with pytest.raises(GarminCliError) as exc:
            read_workout_input(use_stdin=True)
        assert exc.value.error_code == "INVALID_INPUT"

    def test_file_path_none_stdin_true_reads_stdin(self, mocker: Any) -> None:
        _patch_stdin(mocker, _VALID_JSON.encode("utf-8"))
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
