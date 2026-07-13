"""Build the Claude Desktop bundle (dist/garmin-py-<version>.mcpb).

A .mcpb file is a zip archive: manifest.json at the root plus the bootstrap
server entry. The version is read from pyproject.toml and stamped into both
files, so the bundle always installs the matching PyPI release.

Usage: python scripts/build_mcpb.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "__GARMIN_PY_VERSION__"


def build(out_dir: Path) -> Path:
    version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["version"]

    manifest = json.loads((REPO_ROOT / "mcpb" / "manifest.json").read_text())
    manifest["version"] = version

    main_py = (REPO_ROOT / "mcpb" / "main.py").read_text()
    if PLACEHOLDER not in main_py:
        raise SystemExit(f"mcpb/main.py is missing the {PLACEHOLDER} placeholder")
    main_py = main_py.replace(PLACEHOLDER, version)

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
