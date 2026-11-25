"""Domain-agnostic declarative field tables for flat per-row serializers.

This is the generalization of the activity :class:`~garmin_cli.metrics.registry.MetricEntry`
pattern to domains whose rows are *flat* projections of a single wire dict
(health, performance, devices). Those rows have no sport applicability and no
``summaryDTO`` split, so they need a slimmer primitive than ``MetricEntry``:

* :class:`FieldEntry` -- one output column: its ``key``, the precedence-ordered
  ``source_paths`` to try on the wire item, and an optional ``converter``
  applied only to a non-None resolved value (mirrors ``MetricEntry.formatter``).
* :func:`project_row` -- resolve every entry against one wire item, producing a
  row dict whose key set is exactly the table's keys (insertion order matches
  declaration order, so JSON-envelope key order is preserved).
* :class:`FieldTable` -- bundles the entries; its ``columns`` header order is
  derived from them, so the two cannot drift.

``MetricEntry`` deliberately stays separate: it carries activity-only state
(``sports``) and is resolved by the summaryDTO-aware
:func:`~garmin_cli.metrics.registry.resolve`. The precedence walk is shared
(:func:`~garmin_cli.metrics.registry._walk`), so behaviour stays consistent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from garmin_cli.metrics.registry import _walk


@dataclass(frozen=True)
class FieldEntry:
    """Declarative definition of a single flat output field.

    ``key`` is the serializer output key (e.g. ``resting_hr``); Garmin wire
    names live only inside ``source_paths``, each a tuple of nested dict keys
    tried in declared precedence. ``converter`` is applied only when the
    resolved value is not None (None-in/None-out unit transforms).
    """

    key: str
    source_paths: tuple[tuple[str, ...], ...]
    converter: Callable[[Any], Any] | None = None


def resolve_field(entry: FieldEntry, item: dict[str, Any]) -> Any:
    """Resolve one :class:`FieldEntry` against a wire ``item``.

    Walks ``entry.source_paths`` in declared precedence and returns the first
    non-None value, applying ``entry.converter`` to it when present. Returns
    None when no path resolves (the converter is never called with None, so a
    field that is simply absent stays None rather than a converted-None).
    """
    for path in entry.source_paths:
        value = _walk(item, path)
        if value is not None:
            return entry.converter(value) if entry.converter else value
    return None


def project_row(
    item: dict[str, Any],
    entries: tuple[FieldEntry, ...],
) -> dict[str, Any]:
    """Project one wire ``item`` into a row dict over ``entries``.

    The resulting dict has exactly one key per entry, inserted in declaration
    order so that JSON-envelope key ordering matches the legacy hand-written
    serializers byte-for-byte.
    """
    return {entry.key: resolve_field(entry, item) for entry in entries}


@dataclass(frozen=True)
class FieldTable:
    """A bundle of :class:`FieldEntry` rows; ``columns`` follows their order."""

    entries: tuple[FieldEntry, ...]

    @property
    def columns(self) -> tuple[str, ...]:
        """The published CSV/table header order (one column per entry)."""
        return tuple(entry.key for entry in self.entries)

    def project(self, item: dict[str, Any]) -> dict[str, Any]:
        """Project a single wire ``item`` into a row over this table's entries."""
        return project_row(item, self.entries)

    def project_all(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Project a list of wire items into one row each (order preserved)."""
        return [self.project(item) for item in items]
