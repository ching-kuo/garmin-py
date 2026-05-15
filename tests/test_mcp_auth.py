"""Tests for the StaticBearerTokenVerifier (MCP SDK TokenVerifier impl)."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.server.auth.provider import AccessToken  # noqa: E402

from garmin_cli.mcp_auth import StaticBearerTokenVerifier  # noqa: E402


def _verify(verifier: StaticBearerTokenVerifier, token: str) -> AccessToken | None:
    return asyncio.run(verifier.verify_token(token))


class TestStaticBearerTokenVerifierInit:
    """Constructor enforces non-empty, non-whitespace token."""

    def test_stores_token(self) -> None:
        v = StaticBearerTokenVerifier("abc")
        # Must be readable for verify_token to use it; internal-name access is fine
        # in tests since this is the same module's contract.
        result = _verify(v, "abc")
        assert result is not None

    def test_strips_surrounding_whitespace(self) -> None:
        v = StaticBearerTokenVerifier("  abc  ")
        assert _verify(v, "abc") is not None
        assert _verify(v, "  abc  ") is None  # whitespace not stored, so doesn't match

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="GARMIN_MCP_BEARER_TOKEN"):
            StaticBearerTokenVerifier("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="GARMIN_MCP_BEARER_TOKEN"):
            StaticBearerTokenVerifier("   ")

    def test_tab_only_raises(self) -> None:
        with pytest.raises(ValueError, match="GARMIN_MCP_BEARER_TOKEN"):
            StaticBearerTokenVerifier("\t\n")


class TestVerifyToken:

    def test_match_returns_access_token(self) -> None:
        v = StaticBearerTokenVerifier("secret-abc")
        result = _verify(v, "secret-abc")
        assert isinstance(result, AccessToken)
        assert result.token == "secret-abc"
        assert result.client_id == "garmin-cli-mcp"
        assert result.scopes == ["mcp.write"]

    def test_mismatch_returns_none(self) -> None:
        v = StaticBearerTokenVerifier("secret-abc")
        assert _verify(v, "secret-xyz") is None

    def test_empty_token_returns_none(self) -> None:
        v = StaticBearerTokenVerifier("secret-abc")
        assert _verify(v, "") is None

    def test_uses_constant_time_compare(self, mocker: Any) -> None:
        spy = mocker.spy(__import__("hmac"), "compare_digest")
        v = StaticBearerTokenVerifier("secret-abc")
        _verify(v, "secret-abc")
        assert spy.called, "verify_token must use hmac.compare_digest"

    def test_prefix_match_rejected(self) -> None:
        v = StaticBearerTokenVerifier("secret")
        assert _verify(v, "secret-extra") is None
        assert _verify(v, "sec") is None
