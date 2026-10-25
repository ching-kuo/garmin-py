"""Tests for packaging metadata."""
from __future__ import annotations

from pathlib import Path

import tomllib


def test_pyproject_package_discovery_src_only() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text())

    find_config = config["tool"]["setuptools"]["packages"]["find"]
    where = set(find_config.get("where", []))
    include = set(find_config.get("include", []))

    assert where == {"src"}, f"Expected where={{'src'}}, got {where!r}"
    assert "." not in where, "Root '.' must not be in 'where' (shadow package removed)"
    assert "garmin_cli*" in include, "'garmin_cli*' must be in include"
    assert "garmin*" not in include, "'garmin*' must not be in include (shadow package removed)"


def test_runtime_version_matches_pyproject() -> None:
    """__version__ derives from installed metadata, so it must equal the
    single source of truth in pyproject.toml -- guards against the drift that
    left it pinned at 1.2.0 through several releases."""
    from garmin_cli import __version__

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert __version__ == declared, (
        f"garmin_cli.__version__={__version__!r} != pyproject version={declared!r}; "
        "reinstall the package (pip install -e .) to refresh metadata"
    )


def test_cli_version_flag_reports_package_version() -> None:
    """`--version` must surface the package's own `__version__` end-to-end,
    exercising the click version_option wiring. The pyproject<->metadata equality
    is owned by test_runtime_version_matches_pyproject; asserting against
    __version__ here keeps each test failing for exactly one reason."""
    from click.testing import CliRunner

    from garmin_cli import __version__
    from garmin_cli.cli import cli

    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output, f"expected {__version__!r} in {result.output!r}"


def test_console_script_entry_point_loads() -> None:
    """The `garmin-cli` console script must resolve to its `main` entry; a rename
    or typo in pyproject's [project.scripts] ships a broken command that
    import-level tests never exercise. `load()` raises on a bad target, and the
    identity check pins the exact symbol a rename would silently break."""
    from importlib.metadata import entry_points

    from garmin_cli.cli import main

    matches = list(entry_points(group="console_scripts", name="garmin-cli"))
    assert matches, "garmin-cli console_scripts entry point is missing"
    assert matches[0].load() is main
