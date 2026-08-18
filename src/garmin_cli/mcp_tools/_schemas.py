"""Typed MCP response schemas for the stable, locally-owned result shapes."""

from typing import Any

# pydantic rejects ``typing.TypedDict`` on Python < 3.12, so the
# typing_extensions variant keeps schema generation working on 3.10/3.11.
# Optional keys use ``total=False`` bases instead of ``NotRequired`` because
# the MCP SDK resolves TypedDict fields with stdlib ``typing.get_type_hints``,
# which on 3.10 cannot strip the typing_extensions ``NotRequired`` backport
# and pydantic then rejects the leaked qualifier (PydanticForbiddenQualifier).
# Revert to ``NotRequired`` once Python 3.10 support is dropped.
from typing_extensions import TypedDict


# Optional keys must also be nullable: the MCP SDK dumps the generated output
# model without exclude_none, so omitted optional keys reach the wire as null
# and strict clients reject them unless the schema permits null.
class _EnvelopeOptional(TypedDict, total=False):
    total: int | None
    truncated: bool | None
    next_offset: int | None


class Envelope(_EnvelopeOptional):
    """Common response envelope used by list and row-oriented tools."""

    count: int
    rows: list[dict[str, Any]]


class ActivityGetEnvelope(Envelope, total=False):
    """Activity response with optional multisport and capability metadata."""

    children: list[dict[str, Any]] | None
    unavailable: list[dict[str, Any]] | None


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
