"""Typed MCP response schemas for the stable, locally-owned result shapes."""

from typing import Any

# pydantic rejects ``typing.TypedDict`` on Python < 3.12, so the
# typing_extensions variants keep schema generation working on 3.10/3.11.
from typing_extensions import NotRequired, TypedDict


class Envelope(TypedDict):
    """Common response envelope used by list and row-oriented tools."""

    count: int
    rows: list[dict[str, Any]]
    total: NotRequired[int]
    truncated: NotRequired[bool]
    next_offset: NotRequired[int]


class ActivityGetEnvelope(Envelope):
    """Activity response with optional multisport and capability metadata."""

    children: NotRequired[list[dict[str, Any]]]
    unavailable: NotRequired[list[dict[str, Any]]]


class ActivityDetailMetricsEnvelope(Envelope):
    """Activity metric stream response with sampling metadata."""

    samples_total: int
    samples_returned: int
    stride: int


class WriteEnvelope(Envelope):
    """Envelope for write results and validation rows.

    Write operations intentionally keep row payloads open: each operation has
    a different locally-owned success shape, while all validation failures
    share the same ``ok``/``error_code``/``errors`` convention.
    """


class SessionStatus(TypedDict):
    """Session state returned by ``login_status`` and ``submit_mfa_code``."""

    authenticated: bool
    garmin_home: str
