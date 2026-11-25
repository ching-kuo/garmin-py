"""Custom exceptions for garmin-cli."""
from __future__ import annotations

import re


class GarminCliError(Exception):
    """Raised for all expected garmin-cli failures.

    Attributes:
        error: Human-readable error message.
        error_code: Machine-readable error code (e.g. AUTH_FAILED, NOT_FOUND).
        retry_after_seconds: Known wait before a retry can succeed, if any.
    """

    def __init__(
        self, error: str, error_code: str, *, retry_after_seconds: int | None = None
    ) -> None:
        self.error = error
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(error)


def extract_status_code(exc: Exception) -> int | None:
    if hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        return exc.response.status_code
    # GarthHTTPError stores the HTTPError at exc.error.response.status_code
    if hasattr(exc, "error") and hasattr(exc.error, "response") and hasattr(exc.error.response, "status_code"):
        return exc.error.response.status_code
    match = re.search(r"\b([1-5]\d{2})\b", str(exc))
    if match is not None:
        return int(match.group(1))
    return None
