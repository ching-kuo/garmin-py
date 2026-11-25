"""Tests for the domain-agnostic flat field-table core and its adoption.

The existing ``tests/test_serializers.py`` is the byte-identical regression net
for serializer *output*; these tests exercise the new
:mod:`garmin_cli.metrics.field_table` primitives directly and check that
``FieldTable.columns`` (and so every derived ``COLUMNS_*``) follows entry order.
"""
from __future__ import annotations

from typing import Any

import pytest

from garmin_cli.metrics import FieldEntry, FieldTable
from garmin_cli.metrics.field_table import project_row, resolve_field


# ---------------------------------------------------------------------------
# FieldEntry / resolve_field
# ---------------------------------------------------------------------------


class TestResolveField:

    def test_single_path_resolves(self) -> None:
        entry = FieldEntry("k", (("a",),))
        assert resolve_field(entry, {"a": 5}) == 5

    def test_missing_returns_none(self) -> None:
        entry = FieldEntry("k", (("a",),))
        assert resolve_field(entry, {}) is None

    def test_precedence_first_non_none_wins(self) -> None:
        entry = FieldEntry("k", (("a",), ("b",)))
        assert resolve_field(entry, {"a": 1, "b": 2}) == 1

    def test_precedence_falls_through_on_none(self) -> None:
        entry = FieldEntry("k", (("a",), ("b",)))
        assert resolve_field(entry, {"a": None, "b": 2}) == 2

    def test_explicit_none_is_treated_as_absent(self) -> None:
        entry = FieldEntry("k", (("a",),))
        assert resolve_field(entry, {"a": None}) is None

    def test_nested_path_walk(self) -> None:
        entry = FieldEntry("k", (("a", "b", "c"),))
        assert resolve_field(entry, {"a": {"b": {"c": 9}}}) == 9

    def test_nested_path_missing_intermediate(self) -> None:
        entry = FieldEntry("k", (("a", "b", "c"),))
        assert resolve_field(entry, {"a": {}}) is None

    def test_converter_applied_to_non_none(self) -> None:
        entry = FieldEntry("k", (("a",),), lambda v: v / 1000)
        assert resolve_field(entry, {"a": 75000}) == pytest.approx(75.0)

    def test_converter_not_called_on_none(self) -> None:
        called: list[Any] = []

        def conv(value: Any) -> Any:
            called.append(value)
            return value

        entry = FieldEntry("k", (("a",),), conv)
        assert resolve_field(entry, {}) is None
        assert called == []

    def test_zero_is_not_treated_as_absent(self) -> None:
        entry = FieldEntry("k", (("a",), ("b",)), lambda v: v * 2)
        assert resolve_field(entry, {"a": 0, "b": 99}) == 0


# ---------------------------------------------------------------------------
# project_row / FieldTable projection
# ---------------------------------------------------------------------------


class TestProjectRow:

    def test_key_order_matches_declaration(self) -> None:
        entries = (
            FieldEntry("z", (("z",),)),
            FieldEntry("a", (("a",),)),
            FieldEntry("m", (("m",),)),
        )
        row = project_row({"a": 1, "m": 2, "z": 3}, entries)
        assert list(row.keys()) == ["z", "a", "m"]

    def test_row_has_exactly_one_key_per_entry(self) -> None:
        entries = (FieldEntry("a", (("a",),)), FieldEntry("b", (("b",),)))
        row = project_row({"a": 1, "b": 2, "extra": 3}, entries)
        assert set(row) == {"a", "b"}

    def test_table_project_and_project_all(self) -> None:
        table = FieldTable(
            entries=(
                FieldEntry("date", (("calendarDate",),)),
                FieldEntry("v", (("value",),)),
            ),
        )
        assert table.project({"calendarDate": "d", "value": 1}) == {"date": "d", "v": 1}
        assert table.project_all(
            [{"calendarDate": "d1", "value": 1}, {"calendarDate": "d2", "value": 2}]
        ) == [{"date": "d1", "v": 1}, {"date": "d2", "v": 2}]

    def test_empty_item_yields_all_none_row(self) -> None:
        table = FieldTable(
            entries=(FieldEntry("a", (("a",),)), FieldEntry("b", (("b",),))),
        )
        assert table.project({}) == {"a": None, "b": None}

    def test_columns_derive_from_entry_order(self) -> None:
        table = FieldTable(entries=(FieldEntry("z", (("z",),)), FieldEntry("a", (("a",),))))
        assert table.columns == ("z", "a")

    def test_is_frozen(self) -> None:
        table = FieldTable(entries=(FieldEntry("a", (("a",),)),))
        with pytest.raises((AttributeError, Exception)):
            table.entries = ()  # type: ignore[misc]
