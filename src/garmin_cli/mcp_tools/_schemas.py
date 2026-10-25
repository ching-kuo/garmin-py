"""Typed MCP response schemas for the stable, locally-owned result shapes."""

from typing import Any, NotRequired, TypedDict


class Envelope(TypedDict):
    """Common response envelope used by list and row-oriented tools."""

    count: int
    rows: list[dict[str, Any]]
    # Optional keys must also be nullable: the MCP SDK dumps the generated output
    # model without exclude_none, so omitted optional keys reach the wire as null
    # and strict clients reject them unless the schema permits null.
    total: NotRequired[int | None]
    truncated: NotRequired[bool | None]
    next_offset: NotRequired[int | None]


class ActivityGetEnvelope(Envelope):
    """Activity response with optional multisport and capability metadata."""

    children: NotRequired[list[dict[str, Any]] | None]
    unavailable: NotRequired[list[dict[str, Any]] | None]


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
