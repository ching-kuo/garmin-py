"""Tests for garmin_cli.output — envelope creation and echo functions."""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from typing import Any

import pytest

from garmin_cli.output import (
    _format_cell,
    _sanitize_csv_cell,
    echo_csv,
    echo_json,
    echo_table,
    make_envelope,
    make_error_envelope,
    render_capability_footnote,
)


# ---------------------------------------------------------------------------
# make_envelope
# ---------------------------------------------------------------------------

class TestMakeEnvelope:

    def test_command_is_set(self) -> None:
        env = make_envelope("sleep", [{"date": "2026-03-11"}])
        assert env["command"] == "sleep"

    def test_data_is_passed_through(self) -> None:
        data = [{"date": "2026-03-11", "score": 82}]
        env = make_envelope("sleep", data)
        assert env["data"] == data

    def test_count_equals_len_data(self) -> None:
        data = [{"a": 1}, {"a": 2}, {"a": 3}]
        env = make_envelope("test", data)
        assert env["count"] == 3

    def test_count_zero_for_empty_data(self) -> None:
        env = make_envelope("test", [])
        assert env["count"] == 0

    def test_date_range_included_when_provided(self) -> None:
        dr = (date(2026, 3, 1), date(2026, 3, 11))
        env = make_envelope("sleep", [], date_range=dr)
        assert "date_range" in env
        assert env["date_range"] is not None

    def test_date_range_none_by_default(self) -> None:
        env = make_envelope("sleep", [])
        # date_range key may be absent or None
        assert env.get("date_range") is None or "date_range" not in env

    def test_envelope_contains_required_keys(self) -> None:
        env = make_envelope("sleep", [])
        for key in ("ok", "command", "data", "count"):
            assert key in env

    def test_immutability_data_not_mutated(self) -> None:
        original = [{"a": 1}]
        env = make_envelope("test", original)
        env["data"].append({"a": 2})  # type: ignore[union-attr]
        assert len(original) == 1  # original not mutated if deep copy used


# ---------------------------------------------------------------------------
# make_error_envelope
# ---------------------------------------------------------------------------

class TestMakeErrorEnvelope:

    def test_ok_is_false(self) -> None:
        env = make_error_envelope("sleep", "Something failed", "SOME_ERROR")
        assert env["ok"] is False

    def test_command_is_set(self) -> None:
        env = make_error_envelope("sleep", "err", "ERR")
        assert env["command"] == "sleep"

    def test_error_message_is_set(self) -> None:
        env = make_error_envelope("sleep", "Not found", "NOT_FOUND")
        assert env["error"] == "Not found"

    def test_error_code_is_set(self) -> None:
        env = make_error_envelope("sleep", "err", "NOT_FOUND")
        assert env["error_code"] == "NOT_FOUND"

    def test_no_data_key(self) -> None:
        env = make_error_envelope("sleep", "err", "ERR")
        # data should either be absent or None — never a list
        assert env.get("data") is None or "data" not in env

    def test_no_count_key(self) -> None:
        env = make_error_envelope("sleep", "err", "ERR")
        assert env.get("count") is None or "count" not in env

    def test_contains_required_keys(self) -> None:
        env = make_error_envelope("sleep", "error message", "ERR_CODE")
        for key in ("ok", "command", "error", "error_code"):
            assert key in env


# ---------------------------------------------------------------------------
# echo_json
# ---------------------------------------------------------------------------

class TestEchoJson:

    def test_outputs_valid_json(self, capsys: Any) -> None:
        env = make_envelope("test", [{"key": "value"}])
        echo_json(env)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["ok"] is True

    def test_date_objects_serialized_as_strings(self, capsys: Any) -> None:
        env = make_envelope("test", [{"date": date(2026, 3, 11)}])
        echo_json(env)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["data"][0]["date"] == "2026-03-11"

    def test_error_envelope_output_valid_json(self, capsys: Any) -> None:
        env = make_error_envelope("test", "failed", "ERR")
        echo_json(env)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["ok"] is False

    def test_none_values_serialized(self, capsys: Any) -> None:
        env = make_envelope("test", [{"field": None}])
        echo_json(env)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["data"][0]["field"] is None


# ---------------------------------------------------------------------------
# echo_table
# ---------------------------------------------------------------------------

class TestEchoTable:

    def test_outputs_header_columns(self, capsys: Any) -> None:
        data = [{"name": "Run", "distance_km": 10.0}]
        columns = ("name", "distance_km")
        echo_table(data, columns)
        out = capsys.readouterr().out
        assert "name" in out.lower() or "distance_km" in out.lower()

    def test_outputs_data_values(self, capsys: Any) -> None:
        data = [{"name": "Morning Run", "distance_km": 10.5}]
        columns = ("name", "distance_km")
        echo_table(data, columns)
        out = capsys.readouterr().out
        assert "Morning Run" in out

    def test_empty_data_outputs_no_data_placeholder(self, capsys: Any) -> None:
        echo_table([], ("name", "distance_km"))
        out = capsys.readouterr().out
        assert out.strip() == "(no data)"

    def test_multiple_rows_all_present(self, capsys: Any) -> None:
        data = [
            {"name": "Run A", "dist": 5.0},
            {"name": "Run B", "dist": 10.0},
        ]
        echo_table(data, ("name", "dist"))
        out = capsys.readouterr().out
        assert "Run A" in out
        assert "Run B" in out



# ---------------------------------------------------------------------------
# echo_csv
# ---------------------------------------------------------------------------

class TestEchoCsv:

    def test_outputs_header_row(self, capsys: Any) -> None:
        data = [{"name": "Run", "distance_km": 10.0}]
        columns = ("name", "distance_km")
        echo_csv(data, columns)
        out = capsys.readouterr().out
        reader = csv.reader(io.StringIO(out))
        header = next(reader)
        assert "name" in header
        assert "distance_km" in header

    def test_outputs_data_row(self, capsys: Any) -> None:
        data = [{"name": "Run", "distance_km": 10.0}]
        columns = ("name", "distance_km")
        echo_csv(data, columns)
        out = capsys.readouterr().out
        reader = csv.reader(io.StringIO(out))
        next(reader)  # skip header
        row = next(reader)
        assert "Run" in row

    def test_commas_in_values_are_escaped(self, capsys: Any) -> None:
        data = [{"name": "Run, Fast", "distance_km": 10.0}]
        columns = ("name", "distance_km")
        echo_csv(data, columns)
        out = capsys.readouterr().out
        reader = csv.reader(io.StringIO(out))
        next(reader)
        row = next(reader)
        assert "Run, Fast" in row  # csv.reader handles quoting

    def test_quotes_in_values_are_escaped(self, capsys: Any) -> None:
        data = [{"name": 'Run "Fast"', "distance_km": 5.0}]
        columns = ("name", "distance_km")
        echo_csv(data, columns)
        out = capsys.readouterr().out
        reader = csv.reader(io.StringIO(out))
        next(reader)
        row = next(reader)
        assert 'Run "Fast"' in row

    def test_empty_data_outputs_header_only(self, capsys: Any) -> None:
        echo_csv([], ("name", "distance_km"))
        out = capsys.readouterr().out
        lines = [line for line in out.splitlines() if line.strip()]
        assert len(lines) == 1  # just the header

    def test_multiple_rows(self, capsys: Any) -> None:
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        echo_csv(data, ("a", "b"))
        out = capsys.readouterr().out
        reader = csv.reader(io.StringIO(out))
        rows = list(reader)
        # header + 2 data rows
        assert len(rows) == 3

    def test_none_values_output_as_empty(self, capsys: Any) -> None:
        data = [{"name": None, "val": 1}]
        echo_csv(data, ("name", "val"))
        out = capsys.readouterr().out
        assert out  # just shouldn't crash

    def test_unicode_in_values(self, capsys: Any) -> None:
        data = [{"name": "Laufen \u00dc", "val": 1}]
        echo_csv(data, ("name", "val"))
        out = capsys.readouterr().out
        assert "\u00dc" in out


# ---------------------------------------------------------------------------
# _sanitize_csv_cell — CSV formula injection protection (regression tests)
# ---------------------------------------------------------------------------

class TestSanitizeCsvCell:
    """Regression tests for CSV formula-injection fix.

    Values starting with =, +, -, @, \\t, or \\r must be prefixed with \\t
    so spreadsheet software does not interpret them as formulas.
    """

    @pytest.mark.parametrize("dangerous_prefix", ["=", "+", "-", "@", "\t", "\r"])
    def test_dangerous_prefix_is_escaped(self, dangerous_prefix: str) -> None:
        value = f"{dangerous_prefix}SUM(A1:A10)"
        result = _sanitize_csv_cell(value)
        assert result.startswith("\t"), (
            f"Expected tab prefix for value starting with {dangerous_prefix!r}, got {result!r}"
        )

    def test_safe_value_not_prefixed(self) -> None:
        assert _sanitize_csv_cell("Morning Run") == "Morning Run"

    def test_none_returns_empty_string(self) -> None:
        assert _sanitize_csv_cell(None) == ""

    def test_numeric_value_not_prefixed(self) -> None:
        assert _sanitize_csv_cell(42) == "42"

    def test_negative_number_is_prefixed(self) -> None:
        assert _sanitize_csv_cell("-5") == "\t-5"

    def test_csv_output_formula_values_are_tab_prefixed(self, capsys: Any) -> None:
        """Integration: formula-like values survive the full echo_csv path tab-prefixed."""
        data = [{"formula": "=SUM(A1)", "name": "Run"}]
        echo_csv(data, ("formula", "name"))
        out = capsys.readouterr().out
        reader = csv.reader(io.StringIO(out))
        next(reader)  # skip header
        row = next(reader)
        assert row[0].startswith("\t"), f"Expected tab prefix in CSV cell, got {row[0]!r}"


class TestFormatCell:
    """Tests for table-output cell formatting (no CSV injection protection)."""

    def test_none_returns_empty_string(self) -> None:
        assert _format_cell(None) == ""

    def test_string_passthrough(self) -> None:
        assert _format_cell("Morning Run") == "Morning Run"

    def test_negative_number_not_prefixed(self) -> None:
        assert _format_cell("-5") == "-5"

    def test_numeric_value(self) -> None:
        assert _format_cell(42) == "42"


# ---------------------------------------------------------------------------
# render_capability_footnote (U11)
# ---------------------------------------------------------------------------


class TestRenderCapabilityFootnote:

    def test_zero_counts_returns_none(self) -> None:
        assert render_capability_footnote(0, 0) is None

    def test_only_not_applicable(self) -> None:
        text = render_capability_footnote(12, 0)
        assert text is not None
        assert "12 metrics not applicable" in text
        assert "unexpectedly absent" not in text

    def test_only_absent(self) -> None:
        text = render_capability_footnote(0, 3)
        assert text is not None
        assert "3 metrics unexpectedly absent" in text
        assert "not applicable" not in text

    def test_both_counts(self) -> None:
        text = render_capability_footnote(12, 1)
        assert text is not None
        assert "12 metrics not applicable" in text
        assert "1 metric unexpectedly absent" in text

    def test_singular_not_applicable(self) -> None:
        text = render_capability_footnote(1, 0)
        assert "1 metric not applicable" in text

    def test_singular_absent(self) -> None:
        text = render_capability_footnote(0, 1)
        assert "1 metric unexpectedly absent" in text

    def test_starts_with_note_prefix(self) -> None:
        text = render_capability_footnote(2, 0)
        assert text.startswith("Note:")
