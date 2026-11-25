"""The MCP bearer-token rule, dependency-free so doctor runs without the mcp extra."""
from __future__ import annotations

import re

BEARER_ENV = "GARMIN_MCP_BEARER_TOKEN"
MIN_BEARER_TOKEN_LENGTH = 32
BEARER_TOKEN_HINT = 'python -c "import secrets;print(secrets.token_urlsafe(32))"'
# RFC 6750 section 2.1 b64token; secrets.token_urlsafe output always matches.
_B64TOKEN = re.compile(r"[A-Za-z0-9\-._~+/]+=*")


def validate_bearer_token(raw: str) -> str:
    """Return the stripped token, or raise ValueError with a user-facing message."""
    token = (raw or "").strip()
    if not token:
        raise ValueError(f"{BEARER_ENV} must be a non-empty, non-whitespace string")
    if not _B64TOKEN.fullmatch(token):
        raise ValueError(
            f"{BEARER_ENV} may only contain the RFC 6750 token characters "
            "A-Z a-z 0-9 - . _ ~ + / (plus trailing =); generate one with: "
            f"{BEARER_TOKEN_HINT}"
        )
    if len(token) < MIN_BEARER_TOKEN_LENGTH:
        raise ValueError(
            f"{BEARER_ENV} must be at least {MIN_BEARER_TOKEN_LENGTH} "
            f"characters; generate one with: {BEARER_TOKEN_HINT}"
        )
    return token
