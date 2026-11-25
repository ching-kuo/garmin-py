"""Bootstrap entry point for the garmin-py Claude Desktop bundle (.mcpb).

Standard-library only: Claude Desktop launches this file with the user's
system Python. On first launch it creates a private virtual environment and
installs the pinned garmin-py release from PyPI (compiled dependencies such
as pydantic-core cannot be vendored inside the bundle across OS/Python-ABI
combinations); afterwards it hands stdio over to the real MCP server.

stdout belongs to the MCP protocol -- all bootstrap output goes to stderr.
Keep everything before the Python version check in main() parseable and
runnable on old interpreters (3.8, e.g. macOS /usr/bin/python3) so it can
find a newer Python or explain the requirement.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import venv
from collections.abc import MutableMapping
from pathlib import Path

# Replaced with the real release version by scripts/build_mcpb.py.
VERSION = "__GARMIN_PY_VERSION__"
MIN_PYTHON = "__GARMIN_PY_MIN_PYTHON__"
# Exact dependency pins written next to this file by scripts/build_mcpb.py.
_CONSTRAINTS = Path(__file__).with_name("constraints.txt")
_PIP_TIMEOUT_SECONDS = 900
# Set before re-executing under a newer Python so a bad probe cannot loop.
_REEXEC_ENV = "GARMIN_PY_MCPB_REEXEC"


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


def _python_candidates(minimum: tuple[int, ...]) -> list[str]:
    """Homebrew and python.org interpreters at least ``minimum``, oldest minor first.

    GUI apps on macOS get a PATH where ``python3`` is Apple's 3.9. The lowest
    qualifying minor is the one most likely to have wheels for every pin.
    pyenv, asdf, and uv-managed Pythons are not probed.
    """
    major, low = minimum[0], minimum[1]
    return [
        path
        for minor in range(low, low + 21)
        for path in (
            f"/opt/homebrew/bin/python{major}.{minor}",
            f"/usr/local/bin/python{major}.{minor}",
            f"/Library/Frameworks/Python.framework/Versions/{major}.{minor}/bin/python{major}",
        )
        if os.path.isfile(path) and os.access(path, os.X_OK)
    ]


def _python_version(path: str) -> tuple[int, ...] | None:
    """The interpreter's real (major, minor), or None if it does not run cleanly."""
    try:
        result = subprocess.run(
            [path, "-I", "-c", "import sys; print(*sys.version_info[:2])"],
            stdin=subprocess.DEVNULL,  # stdin is the MCP stream
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return tuple(int(part) for part in result.stdout.split())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _pip_install_command(venv_dir: Path, pinned: bool = True) -> list[str]:
    command = [
        str(_venv_python(venv_dir)),
        "-m", "pip", "install", "--quiet", "--isolated", "--disable-pip-version-check",
        "--timeout", "60", "--only-binary=:all:",
    ]
    if pinned and _CONSTRAINTS.exists():
        command += ["--constraint", str(_CONSTRAINTS)]
    return command + [f"garmin-py[mcp]=={VERSION}"]


def _ensure_install(venv_dir: Path) -> None:
    venv_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(venv_dir.parent, 0o700)  # also tightens dirs made by older releases
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

    def fresh_venv() -> None:
        if venv_dir.exists():
            shutil.rmtree(venv_dir)  # broken half-install from an earlier attempt
        venv.EnvBuilder(with_pip=True).create(str(venv_dir))

    # Wheels only (no sdist build hooks run arbitrary code at install time),
    # pip config files and PIP_* ignored (--isolated alone still reads the
    # global pip.conf), and keep the Garmin credentials out of pip's environment.
    pip_env = {k: v for k, v in os.environ.items() if not k.startswith(("GARMIN_", "PIP_"))}
    pip_env["PIP_CONFIG_FILE"] = os.devnull
    deadline = time.monotonic() + _PIP_TIMEOUT_SECONDS  # one budget for both attempts

    def pip_install(pinned: bool) -> None:
        command = _pip_install_command(venv_dir, pinned)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, _PIP_TIMEOUT_SECONDS)
        subprocess.run(
            command,
            check=True,
            timeout=remaining,
            stdout=sys.stderr,
            stderr=sys.stderr,
            env=pip_env,
        )

    fresh_venv()
    try:
        pip_install(pinned=True)
    except subprocess.CalledProcessError:
        if not _CONSTRAINTS.exists():
            raise
        # Pins come from a Linux build; another OS or a newer Python may lack wheels for them.
        _log("pinned install failed, retrying without version pins")
        fresh_venv()
        pip_install(pinned=False)
    marker.touch()
    _log("Install complete.")
    # This install works; drop venvs left behind by older releases/interpreters.
    for sibling in venv_dir.parent.glob("venv-*"):
        if sibling != venv_dir:
            shutil.rmtree(sibling, ignore_errors=True)


_READ_ONLY_ENV = "GARMIN_MCP_READ_ONLY"
_READ_ONLY_PLACEHOLDER = "${user_config.garmin_read_only}"


def _resolve_read_only_setting(environ: MutableMapping[str, str]) -> None:
    """Map an unfilled read-only placeholder to the manifest default (false).

    Only this exact placeholder is defaulted; any other non-boolean value is
    passed on and the server refuses to start with a configuration error.
    """
    if environ.get(_READ_ONLY_ENV) == _READ_ONLY_PLACEHOLDER:
        _log("The read-only setting was not filled in; using its default (off, write tools enabled).")
        environ[_READ_ONLY_ENV] = "false"


def main() -> int:
    if VERSION.startswith("__"):
        _log(
            "This file is an unbuilt template; run scripts/build_mcpb.py and "
            "install the .mcpb it produces instead."
        )
        return 1
    # Runs on any system Python so it can find a newer one or explain the requirement.
    minimum = tuple(int(part) for part in MIN_PYTHON.split("."))
    if sys.version_info < minimum:
        candidates = [] if os.environ.get(_REEXEC_ENV) else _python_candidates(minimum)
        for newer in candidates:
            found = _python_version(newer)
            if found is None or found < minimum:  # a mislabeled or broken install
                continue
            _log(f"Python {sys.version.split()[0]} is too old; switching to {newer}.")
            os.environ[_REEXEC_ENV] = "1"
            try:
                os.execv(newer, [newer, os.path.abspath(__file__)] + sys.argv[1:])
            except OSError as exc:
                _log(f"Could not start {newer}: {exc}")
        _log(
            f"garmin-py needs Python {MIN_PYTHON} or newer; found "
            f"{sys.version.split()[0]}. Install Python from https://www.python.org/downloads/ "
            "and restart Claude Desktop."
        )
        return 1

    _resolve_read_only_setting(os.environ)

    py_tag = f"{sys.version_info.major}.{sys.version_info.minor}"
    venv_dir = Path.home() / ".garmin-py" / "mcpb" / f"venv-{VERSION}-py{py_tag}"

    for attempt in (1, 2):
        try:
            _ensure_install(venv_dir)
        except subprocess.TimeoutExpired:
            _log(
                f"Installing garmin-py timed out after {_PIP_TIMEOUT_SECONDS // 60} minutes. "
                "Check your internet connection and retry."
            )
            return 1
        except subprocess.CalledProcessError as exc:
            _log(f"Installing garmin-py failed: pip exited with status {exc.returncode}; see the pip output above.")
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
