"""Tests for scripts/build_mcpb.py — the Claude Desktop bundle builder."""
from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

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
        assert build_mcpb.PLACEHOLDER not in main_py
        assert f'VERSION = "{__version__}"' in main_py
