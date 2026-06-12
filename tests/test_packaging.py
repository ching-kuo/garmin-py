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
