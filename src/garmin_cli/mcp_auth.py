"""Bearer-token verification for the MCP server's HTTP transports."""
from __future__ import annotations

import hmac

from mcp.server.auth.provider import AccessToken

from garmin_cli.bearer_token import validate_bearer_token


class StaticBearerTokenVerifier:
    """Verify a single configured bearer token using constant-time comparison.

    Implements the MCP SDK's :class:`TokenVerifier` protocol. The MCP SDK
    extracts ``Authorization: Bearer <token>`` headers and delegates the
    verification to :meth:`verify_token`. The constant-time compare here is
    the only protection against timing attacks -- the SDK does not perform
    it itself.

    The token is required at construction time. Empty, whitespace-only, or
    shorter-than-32-character values raise :class:`ValueError` immediately so
    any caller (CLI startup, tests, future programmatic embeds) trips the
    same gate.
    """

    _CLIENT_ID = "garmin-cli-mcp"
    _SCOPES = ("mcp.write",)

    def __init__(self, token: str) -> None:
        self._token = validate_bearer_token(token)

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        # Compare bytes: compare_digest raises TypeError on non-ASCII str.
        if not hmac.compare_digest(token.encode(), self._token.encode()):
            return None
        return AccessToken(
            token=token,
            client_id=self._CLIENT_ID,
            scopes=list(self._SCOPES),
        )
