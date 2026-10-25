"""Tests for scripts/build_mcpb.py — the Claude Desktop bundle builder."""
from __future__ import annotations

import importlib.util
import json
import zipfile
import tomllib
from pathlib import Path

import pytest

from garmin_cli import __version__

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_mcpb.py"
_spec = importlib.util.spec_from_file_location("build_mcpb", _SCRIPT)
assert _spec is not None and _spec.loader is not None
build_mcpb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_mcpb)


class TestBuildMcpb:

    def test_bundle_contents_and_version_stamp(self, tmp_path: Path) -> None:
        bundle_path = build_mcpb.build(tmp_path)

        assert bundle_path == tmp_path / f"garmin-py-{__version__}.mcpb"
        with zipfile.ZipFile(bundle_path) as bundle:
            assert set(bundle.namelist()) == {"manifest.json", "server/main.py"}
            manifest = json.loads(bundle.read("manifest.json"))
            main_py = bundle.read("server/main.py").decode()

        assert manifest["version"] == __version__
        # Security drift guard: the password must stay keychain-stored.
        assert manifest["user_config"]["garmin_password"]["sensitive"] is True
        assert f'VERSION = "{__version__}"' in main_py
        # Python minimum is stamped from pyproject's requires-python.
        requires = tomllib.loads((build_mcpb.REPO_ROOT / "pyproject.toml").read_text())["project"]["requires-python"]
        minimum = requires.removeprefix(">=")
        assert manifest["compatibility"]["runtimes"]["python"] == requires
        assert f"Requires Python {minimum}+" in manifest["long_description"]
        assert f'MIN_PYTHON = "{minimum}"' in main_py
        assert "__GARMIN_PY_" not in json.dumps(manifest) + main_py

    def test_min_python_parses_lower_bound(self) -> None:
        assert build_mcpb.min_python(">=3.12") == "3.12"

    @pytest.mark.parametrize("spec", [">=3.12,<4", "~=3.12", ">=3", ">= 3.12"])
    def test_min_python_rejects_specifiers_main_py_cannot_parse(self, spec: str) -> None:
        with pytest.raises(SystemExit, match="requires-python"):
            build_mcpb.min_python(spec)
