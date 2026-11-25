"""Shared test helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from garmin_cli import doctor


def require_mcp() -> None:
    """Skip unless the ``mcp`` extra is installed in doctor's supported range.

    ``mcp`` has no ``__version__``, so ``pytest.importorskip(minversion=...)``
    would skip every MCP test; the distribution metadata is checked instead,
    against the range ``test_mcp_range_matches_pyproject`` pins to pyproject.
    """
    installed = doctor._installed_version("mcp")
    if installed is None:
        pytest.skip("mcp extra not installed", allow_module_level=True)
    if not doctor._in_supported_range(installed):
        pytest.skip(f"mcp {installed} is outside the supported range", allow_module_level=True)


def make_http_error(status_code: int, message: str | None = None) -> Exception:
    """Create a mock HTTP error with a response.status_code attribute."""
    err = Exception(message or f"HTTP {status_code}")
    err.response = MagicMock(status_code=status_code)  # type: ignore[attr-defined]
    return err


# Registered devices shaped like the live /deviceregistration/devices rows
# (fenix 8: run/cycle/swim; Edge: cycling only; HRM: no workouts).
FENIX = {"deviceId": 11, "displayName": "fenix 8", "workoutCapable": True,
         "runningWorkoutCapable": True, "cyclingWorkoutCapable": True}
EDGE = {"deviceId": 22, "displayName": "Edge 850", "workoutCapable": True,
        "runningWorkoutCapable": False, "cyclingWorkoutCapable": True}
EDGE_1040 = {**EDGE, "deviceId": 23, "displayName": "Edge 1040"}
HRM = {"deviceId": 33, "displayName": "HRM 600", "workoutCapable": False}


def workout(sport: str = "running", workout_id: int = 123) -> dict[str, object]:
    """A saved workout as ``get_workout`` returns it."""
    return {"workoutId": workout_id, "workoutName": "Tempo", "sportType": {"sportTypeKey": sport}}


def make_requests_http_error(status_code: int) -> Exception:
    """A real ``requests.HTTPError`` (an OSError subclass) carrying a real response."""
    import requests

    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} Error", response=response)
