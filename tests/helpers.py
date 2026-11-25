"""Shared test helpers."""
from __future__ import annotations

from unittest.mock import MagicMock


def make_http_error(status_code: int, message: str | None = None) -> Exception:
    """Create a mock HTTP error with a response.status_code attribute."""
    err = Exception(message or f"HTTP {status_code}")
    err.response = MagicMock(status_code=status_code)  # type: ignore[attr-defined]
    return err


def make_requests_http_error(status_code: int) -> Exception:
    """A real ``requests.HTTPError`` (an OSError subclass) carrying a real response."""
    import requests

    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} Error", response=response)
