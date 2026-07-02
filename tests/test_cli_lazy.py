"""Tests for lazy CLI subcommand loading — fast --version/--help without the backend."""
from __future__ import annotations

import importlib
import subprocess
import sys

import click
import pytest
from click.testing import CliRunner

from garmin_cli.cli import _LAZY_SUBCOMMANDS, cli

# Modules that must NOT load for --version/--help: the Garmin backend chain.
_HEAVY_MODULES = ("garminconnect", "requests", "curl_cffi")

_SUBPROCESS_CHECK = """
import sys
from click.testing import CliRunner
from garmin_cli.cli import cli
result = CliRunner().invoke(cli, [{arg!r}])
assert result.exit_code == 0, result.output
loaded = [m for m in {heavy!r} if m in sys.modules]
assert not loaded, f"heavy modules imported eagerly: {{loaded}}"
"""


class TestLazySubcommandLoading:

    @pytest.mark.parametrize("arg", ["--version", "--help"])
    def test_flag_does_not_import_backend(self, arg: str) -> None:
        """Run in a subprocess so the rest of the suite (which imports the
        endpoint modules freely) cannot pollute sys.modules."""
        code = _SUBPROCESS_CHECK.format(arg=arg, heavy=_HEAVY_MODULES)
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        assert proc.returncode == 0, proc.stderr

    def test_help_lists_every_lazy_command(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        for name in _LAZY_SUBCOMMANDS:
            assert name in result.output
        assert "mcp-server" in result.output

    @pytest.mark.parametrize("name", sorted(_LAZY_SUBCOMMANDS))
    def test_static_help_matches_real_command(self, name: str) -> None:
        """The help text in _LAZY_SUBCOMMANDS duplicates each command's
        docstring so --help can render without importing it; fail loudly if
        the two drift apart."""
        module_name, attribute, help_text = _LAZY_SUBCOMMANDS[name]
        real = getattr(importlib.import_module(module_name), attribute)
        assert real.name == name
        stub = click.Command(name, help=help_text)
        for limit in (45, 63, 80):
            assert stub.get_short_help_str(limit) == real.get_short_help_str(limit)

    @pytest.mark.parametrize("name", sorted(_LAZY_SUBCOMMANDS))
    def test_lazy_command_resolves_and_shows_help(self, name: str) -> None:
        result = CliRunner().invoke(cli, [name, "--help"])
        assert result.exit_code == 0, result.output

    def test_unknown_command_still_errors(self) -> None:
        result = CliRunner().invoke(cli, ["no-such-command"])
        assert result.exit_code != 0
