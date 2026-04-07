"""Shared test helpers."""
from __future__ import annotations

from unittest.mock import MagicMock


def make_http_error(status_code: int) -> Exception:
    """Create a mock HTTP error with a response.status_code attribute."""
    err = Exception(f"HTTP {status_code}")
    err.response = MagicMock(status_code=status_code)  # type: ignore[attr-defined]
    return err
