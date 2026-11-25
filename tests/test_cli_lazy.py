"""Tests for lazy CLI subcommand loading — fast --version/--help without the backend."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from typing import Any

import click
import pytest
from click.testing import CliRunner

from garmin_cli.cli import _LAZY_SUBCOMMANDS, _command_name_from_args, cli
from garmin_cli.cli import main as cli_main

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

    def test_lazy_import_failure_still_emits_json_envelope(self, mocker: Any) -> None:
        mocker.patch.dict(cli.commands)
        cli.commands.pop("activity", None)
        mocker.patch(
            "garmin_cli.cli.importlib.import_module", side_effect=ImportError("boom")
        )

        result = CliRunner(mix_stderr=False).invoke(cli, ["--json", "activity", "list"])

        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["error_code"] == "INTERNAL_ERROR"
        assert parsed["command"] == "activity"


def test_command_name_skips_global_option_values() -> None:
    cli.get_command(click.Context(cli), "health")  # ensure the group is loaded

    assert _command_name_from_args(["--garmin-home", "doctor", "health", "sleep"]) == (
        "health sleep"
    )
    assert _command_name_from_args(["--format", "json", "health", "--days", "sleep"]) == (
        "health"
    )


def test_console_entry_point_uses_sys_argv_for_json_errors(
    mocker: Any, capsys: Any
) -> None:
    mocker.patch.object(sys, "argv", ["garmin-cli", "--json", "no-such-command"])
    click_main = mocker.spy(click.Group, "main")

    with pytest.raises(SystemExit) as excinfo:
        cli_main()

    assert excinfo.value.code == 1
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["error_code"] == "INVALID_INPUT"
    # click keeps resolving argv itself (Windows wildcard expansion).
    assert click_main.call_args.kwargs["args"] is None
