"""Tests for the StaticBearerTokenVerifier (MCP SDK TokenVerifier impl)."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.helpers import require_mcp

require_mcp()

from mcp.server.auth.provider import AccessToken  # noqa: E402

from garmin_cli.bearer_token import (  # noqa: E402
    BEARER_ENV,
    BEARER_TOKEN_HINT,
    MIN_BEARER_TOKEN_LENGTH,
)
from garmin_cli.mcp_auth import StaticBearerTokenVerifier  # noqa: E402

_TOKEN = "secret-abc-0123456789-0123456789-xyz"


def _verify(verifier: StaticBearerTokenVerifier, token: str) -> AccessToken | None:
    return asyncio.run(verifier.verify_token(token))


class TestStaticBearerTokenVerifierInit:
    """Constructor enforces a non-empty token of at least the minimum length."""

    def test_stores_token(self) -> None:
        v = StaticBearerTokenVerifier(_TOKEN)
        # Must be readable for verify_token to use it; internal-name access is fine
        # in tests since this is the same module's contract.
        result = _verify(v, _TOKEN)
        assert result is not None

    def test_strips_surrounding_whitespace(self) -> None:
        v = StaticBearerTokenVerifier(f"  {_TOKEN}  ")
        assert _verify(v, _TOKEN) is not None
        assert _verify(v, f"  {_TOKEN}  ") is None  # whitespace not stored, so doesn't match

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match=BEARER_ENV):
            StaticBearerTokenVerifier("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match=BEARER_ENV):
            StaticBearerTokenVerifier("   ")

    def test_tab_only_raises(self) -> None:
        with pytest.raises(ValueError, match=BEARER_ENV):
            StaticBearerTokenVerifier("\t\n")

    def test_short_token_raises_with_generation_hint(self) -> None:
        with pytest.raises(ValueError, match=f"at least {MIN_BEARER_TOKEN_LENGTH}") as excinfo:
            StaticBearerTokenVerifier("a" * (MIN_BEARER_TOKEN_LENGTH - 1))
        assert BEARER_TOKEN_HINT in str(excinfo.value)

    @pytest.mark.parametrize(
        "token", ["ä" * MIN_BEARER_TOKEN_LENGTH, "a b" * MIN_BEARER_TOKEN_LENGTH, "=" + "a" * 40]
    )
    def test_non_b64token_charset_raises(self, token: str) -> None:
        with pytest.raises(ValueError, match=BEARER_ENV):
            StaticBearerTokenVerifier(token)

    def test_token_urlsafe_output_and_padding_accepted(self) -> None:
        import secrets

        for token in (secrets.token_urlsafe(32), "Ab0-._~+/" * 4 + "=="):
            assert _verify(StaticBearerTokenVerifier(token), token) is not None

    def test_minimum_length_token_accepted(self) -> None:
        token = "a" * MIN_BEARER_TOKEN_LENGTH
        assert _verify(StaticBearerTokenVerifier(token), token) is not None


class TestVerifyToken:

    def test_match_returns_access_token(self) -> None:
        v = StaticBearerTokenVerifier(_TOKEN)
        result = _verify(v, _TOKEN)
        assert isinstance(result, AccessToken)
        assert result.token == _TOKEN
        assert result.client_id == "garmin-cli-mcp"
        assert result.scopes == ["mcp.write"]

    def test_mismatch_returns_none(self) -> None:
        v = StaticBearerTokenVerifier(_TOKEN)
        assert _verify(v, _TOKEN[:-3] + "abc") is None

    def test_empty_token_returns_none(self) -> None:
        v = StaticBearerTokenVerifier(_TOKEN)
        assert _verify(v, "") is None

    def test_non_ascii_token_returns_none(self) -> None:
        v = StaticBearerTokenVerifier(_TOKEN)
        assert _verify(v, "sécret-ünicode-token") is None

    def test_uses_constant_time_compare(self, mocker: Any) -> None:
        spy = mocker.spy(__import__("hmac"), "compare_digest")
        v = StaticBearerTokenVerifier(_TOKEN)
        _verify(v, _TOKEN)
        assert spy.called, "verify_token must use hmac.compare_digest"

    def test_prefix_match_rejected(self) -> None:
        v = StaticBearerTokenVerifier(_TOKEN)
        assert _verify(v, _TOKEN + "-extra") is None
        assert _verify(v, _TOKEN[:-1]) is None

    def test_whitespace_padded_incoming_token_rejected(self) -> None:
        """The verifier does NOT strip incoming tokens -- bytes must match exactly."""
        v = StaticBearerTokenVerifier(_TOKEN)
        assert _verify(v, f" {_TOKEN}") is None
        assert _verify(v, f"{_TOKEN} ") is None
        assert _verify(v, f"  {_TOKEN}  ") is None
