"""MCP output schemas: typed only where the outer fields carry meaning."""

from typing import Any, NotRequired, TypedDict

# Generic row-returning tools publish a minimal ``{"type": "object"}`` output
# schema: the shared count/rows/paging contract is described once in the
# server instructions instead of being repeated on every tool.
Envelope = dict[str, Any]


class ActivityGetEnvelope(TypedDict):
    """Activity response with optional multisport and capability metadata."""

    count: int
    rows: list[dict[str, Any]]
    # Optional keys must also be nullable: the MCP SDK dumps the generated output
    # model without exclude_none, so omitted optional keys reach the wire as null
    # and strict clients reject them unless the schema permits null.
    children: NotRequired[list[dict[str, Any]] | None]
    unavailable: NotRequired[list[dict[str, Any]] | None]


class ActivityDetailMetricsEnvelope(TypedDict):
    """Activity metric stream response with sampling metadata."""

    count: int
    rows: list[dict[str, Any]]
    samples_total: int
    samples_returned: int
    stride: int


class SessionStatus(TypedDict):
    """Session state returned by ``login_status`` and ``submit_mfa_code``."""

    authenticated: bool
    garmin_home: str
    # Set when the session could not be checked (RATE_LIMITED, SERVER_ERROR,
    # NETWORK_ERROR): authenticated=false then says nothing about the session.
    error_code: NotRequired[str | None]
    detail: NotRequired[str | None]
