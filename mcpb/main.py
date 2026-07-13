"""Bootstrap entry point for the garmin-py Claude Desktop bundle (.mcpb).

Standard-library only: Claude Desktop launches this file with the user's
system Python. On first launch it creates a private virtual environment and
installs the pinned garmin-py release from PyPI (compiled dependencies such
as pydantic-core cannot be vendored inside the bundle across OS/Python-ABI
combinations); afterwards it hands stdio over to the real MCP server.

stdout belongs to the MCP protocol -- all bootstrap output goes to stderr.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

# Replaced with the real release version by scripts/build_mcpb.py.
VERSION = "__GARMIN_PY_VERSION__"


def _log(message: str) -> None:
    print(f"[garmin-py bootstrap] {message}", file=sys.stderr, flush=True)


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _server_command(venv_dir: Path) -> list[str]:
    if os.name == "nt":
        script = venv_dir / "Scripts" / "garmin-cli.exe"
    else:
        script = venv_dir / "bin" / "garmin-cli"
    return [str(script), "mcp-server"]


def _ensure_install(venv_dir: Path) -> None:
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # ponytail: no inter-process install lock on Windows; a mid-install
        # restart is repaired by the marker check on the next launch
        _install_if_missing(venv_dir)
        return
    import fcntl

    with open(venv_dir.parent / ".install.lock", "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)  # one installer at a time
        _install_if_missing(venv_dir)


def _install_if_missing(venv_dir: Path) -> None:
    marker = venv_dir / ".install-ok"
    if marker.exists():
        return

    _log(f"First launch: installing garmin-py {VERSION} into {venv_dir} ...")
    _log("This needs an internet connection and takes about a minute.")
    if venv_dir.exists():
        shutil.rmtree(venv_dir)  # broken half-install from an earlier attempt
    venv.EnvBuilder(with_pip=True).create(str(venv_dir))
    # Wheels only (no sdist build hooks run arbitrary code at install time),
    # and keep the Garmin credentials out of pip's environment.
    pip_env = {k: v for k, v in os.environ.items() if not k.startswith("GARMIN_")}
    subprocess.run(
        [
            str(_venv_python(venv_dir)),
            "-m", "pip", "install", "--quiet", "--only-binary=:all:",
            f"garmin-py[mcp]=={VERSION}",
        ],
        check=True,
        stdout=sys.stderr,
        stderr=sys.stderr,
        env=pip_env,
    )
    marker.touch()
    _log("Install complete.")
    # This install works; drop venvs left behind by older releases/interpreters.
    for sibling in venv_dir.parent.glob("venv-*"):
        if sibling != venv_dir:
            shutil.rmtree(sibling, ignore_errors=True)


def main() -> int:
    if VERSION.startswith("__"):
        _log(
            "This file is an unbuilt template; run scripts/build_mcpb.py and "
            "install the .mcpb it produces instead."
        )
        return 1
    if sys.version_info < (3, 10):  # noqa: UP036 -- runs on any system Python to explain the requirement
        _log(
            "garmin-py needs Python 3.10 or newer; found "
            f"{sys.version.split()[0]}. Install Python from https://www.python.org/downloads/ "
            "and restart Claude Desktop."
        )
        return 1

    py_tag = f"{sys.version_info.major}.{sys.version_info.minor}"
    venv_dir = Path.home() / ".garmin-py" / "mcpb" / f"venv-{VERSION}-py{py_tag}"

    for attempt in (1, 2):
        try:
            _ensure_install(venv_dir)
        except subprocess.CalledProcessError:
            _log("Installing garmin-py failed. Check your internet connection and retry.")
            return 1
        except OSError as exc:
            _log(f"Setting up the garmin-py environment failed: {exc}")
            return 1

        command = _server_command(venv_dir)
        try:
            if os.name == "nt":
                # exec is emulated on Windows; a forwarding parent is safer there.
                return subprocess.run(command).returncode
            os.execv(command[0], command)  # hand the process (and stdio) to the server
        except OSError:
            # Cached venv points at a vanished interpreter or script (e.g. the
            # Python it was built on was upgraded away). Rebuild once.
            shutil.rmtree(venv_dir, ignore_errors=True)
            if attempt == 1:
                _log("Cached environment is broken; reinstalling ...")
    _log("Could not start the garmin-py server even after reinstalling.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
