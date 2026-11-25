"""CLI integration tests for the MCP server command transport options."""
from __future__ import annotations

import json
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from garmin_cli.bearer_token import BEARER_ENV, BEARER_TOKEN_HINT, MIN_BEARER_TOKEN_LENGTH
from garmin_cli.cli import cli

_VALID_TOKEN = "t" * MIN_BEARER_TOKEN_LENGTH


def _patch_mcp_module(
    mocker: Any,
    server: Any,
    *,
    captured: dict[str, Any] | None = None,
) -> None:
    fake_module = types.ModuleType("garmin_cli.mcp_server")

    def create_mcp_server(config: Any, **kwargs: Any) -> Any:
        if captured is not None:
            captured["config"] = config
            captured["kwargs"] = kwargs
        return server

    fake_module.create_mcp_server = create_mcp_server
    mocker.patch.dict(sys.modules, {"garmin_cli.mcp_server": fake_module})


def _install_fake_mcp_module(mocker: Any) -> tuple[MagicMock, dict[str, Any]]:
    """Patch in a fake mcp_server module so CLI tests stay transport-focused."""
    fake_server = MagicMock()
    captured: dict[str, Any] = {}
    _patch_mcp_module(mocker, fake_server, captured=captured)
    return fake_server, captured


def _combined_output(result: Any) -> str:
    return result.output + (result.stderr or "")


def _serve_args(host: str | None, transport: str = "streamable-http") -> list[str]:
    args = ["mcp-server", "--transport", transport]
    return args if host is None else [*args, "--host", host]


class TestMcpServerCommand:

    def test_mcp_server_defaults_to_stdio_transport(self, mocker: Any) -> None:
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["mcp-server"], catch_exceptions=False)

        assert result.exit_code == 0
        fake_server.run.assert_called_once_with(transport="stdio")

    @pytest.mark.parametrize(
        ("args", "env", "expected"),
        [
            ([], {}, False),
            (["--read-only"], {}, True),
            ([], {"GARMIN_MCP_READ_ONLY": "1"}, True),
            ([], {"GARMIN_MCP_READ_ONLY": "false"}, False),
        ],
    )
    def test_read_only_flag_and_env_reach_the_server(
        self, mocker: Any, args: list[str], env: dict[str, str], expected: bool
    ) -> None:
        _, captured = _install_fake_mcp_module(mocker)
        result = CliRunner(mix_stderr=False).invoke(cli, ["mcp-server", *args], env=env, catch_exceptions=False)

        assert result.exit_code == 0
        assert captured["kwargs"]["read_only"] is expected

    def test_non_boolean_read_only_env_refuses_to_start(self, mocker: Any) -> None:
        fake_server, _ = _install_fake_mcp_module(mocker)
        env = {"GARMIN_MCP_READ_ONLY": "${user_config.garmin_read_only}"}
        result = CliRunner(mix_stderr=False).invoke(cli, ["mcp-server"], env=env)

        assert result.exit_code != 0
        assert "not a valid boolean" in _combined_output(result)
        fake_server.run.assert_not_called()

    def test_mcp_server_accepts_explicit_stdio_transport(self, mocker: Any) -> None:
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            ["mcp-server", "--transport", "stdio"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        fake_server.run.assert_called_once_with(transport="stdio")

    def test_mcp_server_passes_sse_run_options(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv(BEARER_ENV, _VALID_TOKEN)
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            [
                "mcp-server",
                "--transport", "sse",
                "--host", "0.0.0.0",
                "--port", "9000",
                "--sse-path", "/events",
                "--message-path", "/messages",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        fake_server.run.assert_called_once_with(
            transport="sse",
            host="0.0.0.0",
            port=9000,
            sse_path="/events",
            message_path="/messages",
        )

    def test_mcp_server_passes_streamable_http_run_options(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv(BEARER_ENV, _VALID_TOKEN)
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            [
                "mcp-server",
                "--transport", "streamable-http",
                "--host", "0.0.0.0",
                "--port", "9000",
                "--streamable-http-path", "/mcp",
                "--stateless-http",
                "--json-response",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        fake_server.run.assert_called_once_with(
            transport="streamable-http",
            host="0.0.0.0",
            port=9000,
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
        )

    def test_stdio_rejects_http_only_options(self, mocker: Any) -> None:
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            [
                "mcp-server",
                "--transport", "stdio",
                "--host", "0.0.0.0",
            ],
        )

        assert result.exit_code == 1
        assert "http-only" in _combined_output(result).lower()
        fake_server.run.assert_not_called()

    def test_sse_rejects_streamable_http_only_options(self, mocker: Any) -> None:
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            [
                "mcp-server",
                "--transport", "sse",
                "--streamable-http-path", "/mcp",
            ],
        )

        assert result.exit_code == 1
        assert "streamable-http" in _combined_output(result).lower()
        fake_server.run.assert_not_called()

    def test_streamable_http_rejects_sse_only_options(self, mocker: Any) -> None:
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            [
                "mcp-server",
                "--transport", "streamable-http",
                "--sse-path", "/events",
            ],
        )

        assert result.exit_code == 1
        assert "sse" in _combined_output(result).lower()
        fake_server.run.assert_not_called()

    @pytest.mark.parametrize("transport", ["sse", "streamable-http"])
    def test_mount_path_rejected_in_mcp_v2(self, mocker: Any, transport: str) -> None:
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            [
                "mcp-server",
                "--transport", transport,
                "--mount-path", "/garmin",
            ],
        )

        assert result.exit_code == 1
        combined = _combined_output(result).lower()
        assert "--mount-path" in combined
        assert "mcp v2" in combined
        fake_server.run.assert_not_called()

    def test_real_mcpserver_sse_transport_uses_supported_run_kwargs(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        pytest.importorskip("mcp")
        monkeypatch.setenv(BEARER_ENV, _VALID_TOKEN)
        from mcp.server.mcpserver import MCPServer

        real_server = MCPServer("garmin")
        mocker.patch.object(real_server, "run")
        _patch_mcp_module(mocker, real_server)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            [
                "mcp-server",
                "--transport", "sse",
                "--host", "0.0.0.0",
                "--port", "9000",
                "--sse-path", "/events",
                "--message-path", "/messages",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        real_server.run.assert_called_once_with(
            transport="sse",
            host="0.0.0.0",
            port=9000,
            sse_path="/events",
            message_path="/messages",
        )

    def test_real_mcpserver_streamable_http_uses_supported_run_kwargs(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        pytest.importorskip("mcp")
        monkeypatch.setenv(BEARER_ENV, _VALID_TOKEN)
        from mcp.server.mcpserver import MCPServer

        real_server = MCPServer("garmin")
        mocker.patch.object(real_server, "run")
        _patch_mcp_module(mocker, real_server)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            [
                "mcp-server",
                "--transport", "streamable-http",
                "--host", "0.0.0.0",
                "--port", "9000",
                "--streamable-http-path", "/custom-mcp",
                "--stateless-http",
                "--json-response",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        real_server.run.assert_called_once_with(
            transport="streamable-http",
            host="0.0.0.0",
            port=9000,
            streamable_http_path="/custom-mcp",
            stateless_http=True,
            json_response=True,
        )


class TestMcpServerLoopbackDefault:
    """Non-stdio transports default to loopback unless --host overrides."""

    @pytest.mark.parametrize("transport", ["sse", "streamable-http"])
    def test_default_host_is_loopback(
        self, mocker: Any, transport: str, monkeypatch: Any
    ) -> None:
        monkeypatch.delenv(BEARER_ENV, raising=False)
        fake_server, captured = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli, ["mcp-server", "--transport", transport], catch_exceptions=False
        )

        assert result.exit_code == 0
        fake_server.run.assert_called_once()
        call_kwargs = fake_server.run.call_args.kwargs
        assert call_kwargs["host"] == "127.0.0.1"
        # Loopback default skips the auth wiring entirely.
        assert captured["kwargs"].get("token_verifier") is None
        assert captured["kwargs"].get("auth") is None

    @pytest.mark.parametrize(
        "host", ["127.0.0.1", "localhost", "::1"]
    )
    def test_explicit_loopback_skips_auth(
        self, mocker: Any, host: str, monkeypatch: Any
    ) -> None:
        monkeypatch.delenv(BEARER_ENV, raising=False)
        fake_server, captured = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            ["mcp-server", "--transport", "streamable-http", "--host", host],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert captured["kwargs"].get("token_verifier") is None
        assert captured["kwargs"].get("auth") is None

    def test_stdio_ignores_bearer_token(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv(BEARER_ENV, "ignored-on-stdio")
        fake_server, captured = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli, ["mcp-server", "--transport", "stdio"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert captured["kwargs"].get("token_verifier") is None
        assert captured["kwargs"].get("auth") is None

    @pytest.mark.parametrize("host", [None, "127.0.0.1", "localhost", "::1"])
    def test_loopback_enforces_bearer_token_when_set(
        self, mocker: Any, host: str | None, monkeypatch: Any
    ) -> None:
        pytest.importorskip("mcp")
        from garmin_cli.mcp_auth import StaticBearerTokenVerifier

        monkeypatch.setenv(BEARER_ENV, _VALID_TOKEN)
        fake_server, captured = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)
        args = ["mcp-server", "--transport", "streamable-http"]
        if host is not None:
            args += ["--host", host]

        result = runner.invoke(cli, args, catch_exceptions=False)

        assert result.exit_code == 0
        assert isinstance(captured["kwargs"]["token_verifier"], StaticBearerTokenVerifier)
        assert captured["kwargs"]["auth"] is not None

    @pytest.mark.parametrize(
        ("host", "bound", "expected_url"),
        [(None, "127.0.0.1", "http://127.0.0.1:8000"),
         ("::1", "::1", "http://[::1]:8000"),
         ("[::1]", "::1", "http://[::1]:8000")],
    )
    def test_bind_host_is_normalized_once_for_run_and_auth(
        self, mocker: Any, monkeypatch: Any, host: str | None, bound: str, expected_url: str
    ) -> None:
        pytest.importorskip("mcp")
        monkeypatch.setenv(BEARER_ENV, _VALID_TOKEN)
        fake_server, captured = _install_fake_mcp_module(mocker)
        args = ["mcp-server", "--transport", "streamable-http"]
        if host is not None:
            args += ["--host", host]

        result = CliRunner(mix_stderr=False).invoke(cli, args, catch_exceptions=False)

        assert result.exit_code == 0
        assert fake_server.run.call_args.kwargs["host"] == bound
        assert str(captured["kwargs"]["auth"].issuer_url).rstrip("/") == expected_url

    def test_json_token_refusal_is_invalid_input(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv(BEARER_ENV, "too-short")
        _install_fake_mcp_module(mocker)

        result = CliRunner(mix_stderr=False).invoke(
            cli, ["--json", "mcp-server", "--transport", "sse"]
        )

        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["error_code"] == "INVALID_INPUT"
        assert parsed["command"] == "mcp-server"
        assert f"at least {MIN_BEARER_TOKEN_LENGTH}" in parsed["error"]

    @pytest.mark.parametrize("host", ["[]", "[", "]", "[localhost]", " "])
    def test_malformed_host_is_rejected(
        self, mocker: Any, monkeypatch: Any, host: str
    ) -> None:
        # These used to normalize to "" -> treated as loopback, while the
        # HTTP server bound every interface unauthenticated.
        monkeypatch.delenv(BEARER_ENV, raising=False)
        fake_server, _ = _install_fake_mcp_module(mocker)

        result = CliRunner(mix_stderr=False).invoke(cli, _serve_args(host))

        assert result.exit_code != 0
        assert "--host" in _combined_output(result)
        fake_server.run.assert_not_called()


_SHORT = f"at least {MIN_BEARER_TOKEN_LENGTH}"


class TestMcpServerTokenRefusals:
    """Every invalid or missing-but-required token refuses to start."""

    @pytest.mark.parametrize(
        ("token", "host", "transport", "expected"),
        [
            # Non-loopback binds require the variable.
            (None, "0.0.0.0", "sse", (BEARER_ENV,)),
            (None, "0.0.0.0", "streamable-http", (BEARER_ENV,)),
            # Present but blank refuses on every HTTP bind, loopback included.
            ("", "0.0.0.0", "sse", (BEARER_ENV,)),
            ("   \t  ", "0.0.0.0", "streamable-http", (BEARER_ENV,)),
            ("", None, "streamable-http", (BEARER_ENV,)),
            ("   \t  ", "127.0.0.1", "streamable-http", (BEARER_ENV,)),
            # Too short or outside the RFC 6750 alphabet.
            ("too-short", None, "sse", (_SHORT, BEARER_TOKEN_HINT)),
            ("t" * (MIN_BEARER_TOKEN_LENGTH - 1), "0.0.0.0", "sse", (_SHORT,)),
            ("ä" * MIN_BEARER_TOKEN_LENGTH, None, "sse", ("RFC 6750", BEARER_TOKEN_HINT)),
            ("a b" * MIN_BEARER_TOKEN_LENGTH, None, "sse", ("RFC 6750",)),
        ],
    )
    def test_refuses_to_start(
        self,
        mocker: Any,
        monkeypatch: Any,
        token: str | None,
        host: str | None,
        transport: str,
        expected: tuple[str, ...],
    ) -> None:
        if token is None:
            monkeypatch.delenv(BEARER_ENV, raising=False)
        else:
            monkeypatch.setenv(BEARER_ENV, token)
        fake_server, _ = _install_fake_mcp_module(mocker)

        result = CliRunner(mix_stderr=False).invoke(cli, _serve_args(host, transport))

        assert result.exit_code != 0
        combined = _combined_output(result)
        for text in expected:
            assert text in combined
        fake_server.run.assert_not_called()


class TestMcpServerNonLoopbackAuth:
    """Non-loopback HTTP binds wire the bearer verifier and auth settings."""

    def test_valid_token_wires_verifier_and_auth(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        pytest.importorskip("mcp")
        from mcp.server.auth.settings import AuthSettings

        from garmin_cli.mcp_auth import StaticBearerTokenVerifier

        monkeypatch.setenv(BEARER_ENV, _VALID_TOKEN)
        fake_server, captured = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            ["mcp-server", "--transport", "sse", "--host", "0.0.0.0"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        verifier = captured["kwargs"]["token_verifier"]
        auth_settings = captured["kwargs"]["auth"]
        assert isinstance(verifier, StaticBearerTokenVerifier)
        assert isinstance(auth_settings, AuthSettings)
        # AuthSettings URLs reflect the actual bind host and a default port
        # when no --port is supplied.
        assert "0.0.0.0" in str(auth_settings.issuer_url)
        assert "0.0.0.0" in str(auth_settings.resource_server_url)
        assert auth_settings.validate_token_resource is False

    def test_auth_settings_url_uses_supplied_port(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        pytest.importorskip("mcp")
        monkeypatch.setenv(BEARER_ENV, _VALID_TOKEN)
        fake_server, captured = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            [
                "mcp-server",
                "--transport", "streamable-http",
                "--host", "0.0.0.0",
                "--port", "9443",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        auth_settings = captured["kwargs"]["auth"]
        assert "9443" in str(auth_settings.issuer_url)
        assert "9443" in str(auth_settings.resource_server_url)


def test_bearer_token_not_logged(
    mocker: Any, monkeypatch: Any, capsys: Any
) -> None:
    """The canary bearer-token value must not appear in CLI output streams."""
    canary = "secret-canary-abc123-do-not-log-0123456789"
    monkeypatch.setenv(BEARER_ENV, canary)
    fake_server, _ = _install_fake_mcp_module(mocker)
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(
        cli,
        ["mcp-server", "--transport", "streamable-http", "--host", "0.0.0.0"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    combined = result.output + (result.stderr or "")
    assert canary not in combined


@pytest.mark.parametrize("transport", ["stdio", "sse", "streamable-http"])
def test_mcp_import_guard_covers_all_transports(mocker: Any, transport: str) -> None:
    mocker.patch.dict(sys.modules, {"garmin_cli.mcp_server": None})
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(
        cli,
        ["mcp-server", "--transport", transport],
    )

    assert result.exit_code == 1
    combined = _combined_output(result)
    assert 'pip install "garmin-py[mcp]"' in combined


def test_mcp_import_guard_emits_json_envelope(mocker: Any) -> None:
    mocker.patch.dict(sys.modules, {"garmin_cli.mcp_server": None})

    result = CliRunner(mix_stderr=False).invoke(cli, ["--json", "mcp-server"])

    assert result.exit_code == 1
    parsed = json.loads(result.output)
    assert parsed["ok"] is False
    assert parsed["command"] == "mcp-server"
    assert 'pip install "garmin-py[mcp]"' in parsed["error"]
