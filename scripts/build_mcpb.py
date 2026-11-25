"""Build the Claude Desktop bundle (dist/garmin-py-<version>.mcpb).

A .mcpb file is a zip archive: manifest.json at the root plus the bootstrap
server entry. The version is read from pyproject.toml and stamped into both
files, so the bundle always installs the matching PyPI release. The
minimum Python (``requires-python``) is stamped into main.py and the manifest's
description; the manifest's ``compatibility.runtimes.python`` stays ">=3.8",
the oldest Python main.py can start on to switch to a newer one, because
Claude Desktop checks it against ``python3`` on PATH. The bundle also
ships server/constraints.txt: exact pins for the runtime + mcp dependencies,
resolved from PyPI at build time (needs network and pip in this interpreter).

Usage: python scripts/build_mcpb.py [--out DIR]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "__GARMIN_PY_VERSION__"
MIN_PYTHON_PLACEHOLDER = "__GARMIN_PY_MIN_PYTHON__"


def min_python(requires_python: str) -> str:
    """Return "X.Y" from a ">=X.Y" specifier; mcpb/main.py parses it as dotted ints."""
    match = re.fullmatch(r">=(\d+\.\d+)", requires_python)
    if match is None:
        raise SystemExit(f'requires-python must be ">=X.Y" for the bundle, got {requires_python!r}')
    return match.group(1)


def _stamp(name: str, text: str, values: dict[str, str]) -> str:
    for placeholder, value in values.items():
        if placeholder not in text:
            raise SystemExit(f"mcpb/{name} is missing the {placeholder} placeholder")
        text = text.replace(placeholder, value)
    return text


def constraints(project: dict[str, Any]) -> str:
    """Exact ``name==version`` pins pip resolves for the bundle's dependencies.

    shortcut: no hashes, and pins are resolved for this build platform and
    Python, so mcpb/main.py retries without them when they fail to install
    elsewhere; upgrade to a hash-locked, multi-platform lock file if a lock
    tool is adopted.
    """
    if importlib.util.find_spec("pip") is None:
        raise SystemExit(f"build_mcpb.py needs pip in {sys.executable} to resolve the bundle's constraints")
    requirements = project["dependencies"] + project["optional-dependencies"]["mcp"]
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "report.json"
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                "--only-binary=:all:", "--quiet", "--isolated", "--disable-pip-version-check",
                "--report", str(report_path), *requirements,
            ],
            check=True,
            # Same resolver settings as the bundle: no pip config, no PIP_* overrides.
            env={**{k: v for k, v in os.environ.items() if not k.startswith("PIP_")}, "PIP_CONFIG_FILE": os.devnull},
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
    pins = sorted(f"{item['metadata']['name']}=={item['metadata']['version']}" for item in report["install"])
    return "\n".join(pins) + "\n"


def build(out_dir: Path) -> Path:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pins = constraints(project)
    version = project["version"]
    minimum = min_python(project["requires-python"])

    manifest_text = (REPO_ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(_stamp("manifest.json", manifest_text, {MIN_PYTHON_PLACEHOLDER: minimum}))
    manifest["version"] = version

    main_py = (REPO_ROOT / "mcpb" / "main.py").read_text(encoding="utf-8")
    main_py = _stamp("main.py", main_py, {PLACEHOLDER: version, MIN_PYTHON_PLACEHOLDER: minimum})

    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = out_dir / f"garmin-py-{version}.mcpb"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        bundle.writestr("server/main.py", main_py)
        bundle.writestr("server/constraints.txt", pins)
    return bundle_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "dist")
    args = parser.parse_args()
    bundle_path = build(args.out)
    print(bundle_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
