"""Tests for packaging metadata."""
from __future__ import annotations

from pathlib import Path
import tomllib


def test_pyproject_package_discovery_includes_src() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text())

    find_config = config["tool"]["setuptools"]["packages"]["find"]
    where = set(find_config.get("where", []))
    include = set(find_config.get("include", []))

    assert "src" in where
    assert "garmin_cli*" in include
