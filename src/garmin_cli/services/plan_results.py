"""Result shapes of training-plan preview and writes (pure, no Garmin calls)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def write_result(
    outcome: str,
    operations: Iterable[dict[str, Any]] = (),
    *,
    complete: bool = False,
    errors: Iterable[dict[str, Any]] = (),
    conflicts: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """A plan-write result: outcome plus the operations, errors and conflicts behind it."""
    return {
        "complete": complete,
        "outcome": outcome,
        "operations": list(operations),
        "errors": list(errors),
        "conflicts": list(conflicts),
    }


def invalid_plan_result(errors: list[str]) -> dict[str, Any]:
    """The no-op result for a plan that failed validation with *errors*."""
    return {
        "complete": False,
        "outcome": "no_op",
        "operations": [],
        "errors": [{"error_code": "INVALID_INPUT", "message": error} for error in errors],
        "conflicts": [],
        "summary": {},
    }
