"""Build the Claude Desktop bundle (dist/garmin-py-<version>.mcpb).

A .mcpb file is a zip archive: manifest.json at the root plus the bootstrap
server entry. The version is read from pyproject.toml and stamped into both
files, so the bundle always installs the matching PyPI release. The
minimum Python (``requires-python``) is stamped the same way.

Usage: python scripts/build_mcpb.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

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


def build(out_dir: Path) -> Path:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    version = project["version"]
    minimum = min_python(project["requires-python"])

    manifest_text = (REPO_ROOT / "mcpb" / "manifest.json").read_text()
    manifest = json.loads(_stamp("manifest.json", manifest_text, {MIN_PYTHON_PLACEHOLDER: minimum}))
    manifest["version"] = version

    main_py = (REPO_ROOT / "mcpb" / "main.py").read_text()
    main_py = _stamp("main.py", main_py, {PLACEHOLDER: version, MIN_PYTHON_PLACEHOLDER: minimum})

    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = out_dir / f"garmin-py-{version}.mcpb"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        bundle.writestr("server/main.py", main_py)
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
