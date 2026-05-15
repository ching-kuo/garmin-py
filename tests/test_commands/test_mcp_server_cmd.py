"""CLI integration tests for the MCP server command transport options."""
from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli


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


class TestMcpServerCommand:

    def test_mcp_server_defaults_to_stdio_transport(self, mocker: Any) -> None:
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(cli, ["mcp-server"], catch_exceptions=False)

        assert result.exit_code == 0
        fake_server.run.assert_called_once_with(transport="stdio")

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
        monkeypatch.setenv("GARMIN_MCP_BEARER_TOKEN", "test-token")
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
        monkeypatch.setenv("GARMIN_MCP_BEARER_TOKEN", "test-token")
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
        monkeypatch.setenv("GARMIN_MCP_BEARER_TOKEN", "test-token")
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
        monkeypatch.setenv("GARMIN_MCP_BEARER_TOKEN", "test-token")
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
        monkeypatch.delenv("GARMIN_MCP_BEARER_TOKEN", raising=False)
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
        monkeypatch.delenv("GARMIN_MCP_BEARER_TOKEN", raising=False)
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
        monkeypatch.setenv("GARMIN_MCP_BEARER_TOKEN", "ignored-on-stdio")
        fake_server, captured = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli, ["mcp-server", "--transport", "stdio"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert captured["kwargs"].get("token_verifier") is None
        assert captured["kwargs"].get("auth") is None


class TestMcpServerNonLoopbackAuth:
    """Non-loopback HTTP binds require GARMIN_MCP_BEARER_TOKEN."""

    @pytest.mark.parametrize("transport", ["sse", "streamable-http"])
    def test_unset_bearer_token_refused(
        self, mocker: Any, transport: str, monkeypatch: Any
    ) -> None:
        monkeypatch.delenv("GARMIN_MCP_BEARER_TOKEN", raising=False)
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            ["mcp-server", "--transport", transport, "--host", "0.0.0.0"],
        )

        assert result.exit_code != 0
        combined = _combined_output(result)
        assert "GARMIN_MCP_BEARER_TOKEN" in combined
        fake_server.run.assert_not_called()

    def test_empty_bearer_token_refused(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("GARMIN_MCP_BEARER_TOKEN", "")
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            ["mcp-server", "--transport", "sse", "--host", "0.0.0.0"],
        )

        assert result.exit_code != 0
        assert "GARMIN_MCP_BEARER_TOKEN" in _combined_output(result)
        fake_server.run.assert_not_called()

    def test_whitespace_bearer_token_refused(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("GARMIN_MCP_BEARER_TOKEN", "   \t  ")
        fake_server, _ = _install_fake_mcp_module(mocker)
        runner = CliRunner(mix_stderr=False)

        result = runner.invoke(
            cli,
            ["mcp-server", "--transport", "streamable-http", "--host", "0.0.0.0"],
        )

        assert result.exit_code != 0
        assert "GARMIN_MCP_BEARER_TOKEN" in _combined_output(result)
        fake_server.run.assert_not_called()

    def test_valid_token_wires_verifier_and_auth(
        self, mocker: Any, monkeypatch: Any
    ) -> None:
        pytest.importorskip("mcp")
        from mcp.server.auth.settings import AuthSettings

        from garmin_cli.mcp_auth import StaticBearerTokenVerifier

        monkeypatch.setenv("GARMIN_MCP_BEARER_TOKEN", "secret-canary-abc123")
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


def test_bearer_token_not_logged(
    mocker: Any, monkeypatch: Any, capsys: Any
) -> None:
    """The canary bearer-token value must not appear in CLI output streams."""
    canary = "secret-canary-abc123-do-not-log"
    monkeypatch.setenv("GARMIN_MCP_BEARER_TOKEN", canary)
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
    assert 'pip install "garmin-cli[mcp]"' in combined
