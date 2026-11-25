"""Non-raising environment and session diagnostics."""
from __future__ import annotations

import os
import re
import stat
import sys
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Callable

from garmin_cli.auth import probe_session_status
from garmin_cli.config import GARTH_HOME_HINT, CliConfig, garth_home_ignored
from garmin_cli.error_contracts import error_contract
from garmin_cli.bearer_token import BEARER_ENV, validate_bearer_token
from garmin_cli.read_only import READ_ONLY_ENV, READ_ONLY_FALSE, READ_ONLY_TRUE
from garmin_cli.exceptions import GarminCliError
from garmin_cli.token_store import (
    TOKEN_FILE_NAME,
    expand_garmin_home,
    tokenstore_path,
    validate_garmin_home,
)


@dataclass(frozen=True)
class CheckResult:
    """One doctor check suitable for CLI and MCP serialization."""

    name: str
    ok: bool
    detail: str
    error_code: str | None = None
    recovery_hint: str | None = None

    def to_row(self) -> dict[str, object]:
        return asdict(self)


# Must match pyproject's `mcp[cli]>=2.2.0,<3` (tests/test_doctor.py checks it).
MIN_MCP_VERSION = (2, 2, 0)
MCP_MAJOR_CEILING = 3
_ENV_CREDENTIALS = (
    "GARMIN_EMAIL and GARMIN_PASSWORD are set, so commands will sign in; "
    "credentials not verified (no session yet)."
)


def _failure(name: str, detail: str, error_code: str, hint: str | None = None) -> CheckResult:
    return CheckResult(
        name=name,
        ok=False,
        detail=detail,
        error_code=error_code,
        recovery_hint=hint or error_contract(error_code)["recovery_hint"],
    )


def _has_env_credentials(config: CliConfig) -> bool:
    return bool(config.email and config.password)


def _installed_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _display_path(path: Path) -> str:
    """Render a path relative to the home directory when possible."""
    try:
        return "~/" + str(path.resolve().relative_to(Path.home().resolve()))
    except (OSError, ValueError):
        return f"<custom>/{path.name}" if path.name else "<custom>"


def check_python_version(_config: CliConfig) -> CheckResult:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 12):  # noqa: UP036 - doctor reports runtime support
        return CheckResult("python_version", True, f"Python {version} is supported.")
    return _failure(
        "python_version",
        f"Python {version} is unsupported; Python 3.12 or newer is required.",
        "INVALID_INPUT",
        "Install Python 3.12 or newer, then reinstall garmin-py with it.",
    )


def check_versions(_config: CliConfig) -> CheckResult:
    garmin_py = _installed_version("garmin-py") or "unknown"
    garminconnect = _installed_version("garminconnect") or "not installed"
    return CheckResult("versions", True, f"garmin-py {garmin_py}; garminconnect {garminconnect}.")


def check_config(config: CliConfig) -> CheckResult:
    path = expand_garmin_home(config.garth_home)
    shown = _display_path(path)
    try:
        validate_garmin_home(str(path))
    except GarminCliError as exc:
        hint = (
            "Point --garmin-home or GARMIN_HOME at a directory, not a file."
            if exc.error_code == "INVALID_INPUT"
            else None
        )
        return _failure("config", exc.error, exc.error_code, hint)  # names the offending link
    if not path.exists():
        if _has_env_credentials(config):
            return CheckResult(
                "config", True, f"Garmin home {shown} does not exist yet; {_ENV_CREDENTIALS}"
            )
        return _failure(
            "config",
            f"Garmin home {shown} does not exist.",
            "AUTH_MISSING",
        )
    return CheckResult("config", True, f"Garmin home resolves to {shown}.")


def check_legacy_garth(config: CliConfig) -> CheckResult:
    """Informational only: point garth-era (pre-3.0) users at GARMIN_HOME."""
    notes = [GARTH_HOME_HINT] if garth_home_ignored(config.garth_home) else []
    legacy_home = expand_garmin_home("~/.garth")
    legacy_token = legacy_home / TOKEN_FILE_NAME
    try:
        # lstat: a symlinked ~/.garth or token file is ignored, never followed.
        if (
            stat.S_ISDIR(legacy_home.lstat().st_mode)
            and stat.S_ISREG(legacy_token.lstat().st_mode)
            and not _same_file(legacy_token, tokenstore_path(config.garth_home))
        ):
            notes.append(
                f"~/.garth/{TOKEN_FILE_NAME} is not used (GARMIN_HOME points elsewhere); "
                "set GARMIN_HOME=~/.garth to use it."
            )
    except FileNotFoundError:
        pass
    except OSError:
        notes.append("Could not inspect ~/.garth.")
    return CheckResult("legacy_garth", True, " ".join(notes) or "No legacy garth settings found.")


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def check_token_store(config: CliConfig) -> CheckResult:
    path = expand_garmin_home(config.garth_home)
    try:
        result = _check_token_store(path)
        if result.error_code == "AUTH_MISSING" and _has_env_credentials(config):
            return CheckResult("token_store", True, f"No token store yet; {_ENV_CREDENTIALS}")
        return result
    except OSError:
        return _failure(
            "token_store",
            f"Token store in {_display_path(path)} cannot be inspected.",
            "AUTH_FAILED",
        )


def _check_token_store(path: Path) -> CheckResult:
    shown = _display_path(path)
    token_file = tokenstore_path(str(path))
    try:
        token_stat = token_file.lstat()  # lstat: a dangling symlink is reported, not "missing"
    except FileNotFoundError:
        return _failure(
            "token_store",
            f"No token store was found in {shown}.",
            "AUTH_MISSING",
        )
    replace_hint = f"Remove {TOKEN_FILE_NAME} from the Garmin home folder, then run garmin-cli login."
    if stat.S_ISLNK(token_stat.st_mode):
        return _failure(
            "token_store", f"Token file {TOKEN_FILE_NAME} is a symlink.", "AUTH_FAILED", replace_hint
        )
    if not stat.S_ISREG(token_stat.st_mode):
        return _failure(
            "token_store",
            f"Token file {TOKEN_FILE_NAME} is not a regular file.",
            "AUTH_FAILED",
            replace_hint,
        )
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o700:
        return _failure(
            "token_store",
            f"Token-store directory permissions are {mode:04o}; expected 0700.",
            "AUTH_FAILED",
            "Restrict the Garmin home folder to owner-only access (mode 700).",
        )
    file_mode = stat.S_IMODE(token_stat.st_mode)
    if file_mode != 0o600:
        return _failure(
            "token_store",
            f"Token file {TOKEN_FILE_NAME} permissions are {file_mode:04o}; expected 0600.",
            "AUTH_FAILED",
            f"Restrict {TOKEN_FILE_NAME} to owner read/write (mode 600).",
        )
    return CheckResult(
        "token_store", True, "Token store is present with 0700 directory and 0600 file permissions."
    )


_PEP440 = re.compile(r"(?:(\d+)!)?(\d+(?:\.\d+)*)(.*)")
_PRE_RELEASE = re.compile(r"[-_.]?(a|b|c|rc|alpha|beta|pre|preview|dev)", re.IGNORECASE)


def _in_supported_range(version: str) -> bool:
    """PEP 440 ``MIN_MCP_VERSION <= version < MCP_MAJOR_CEILING`` for the common
    cases, without ``packaging``. A pre-release or dev build sorts below its
    release (2.2.0rc1 < 2.2.0; 3.0.0rc1 is outside ``<3``).
    """
    match = _PEP440.fullmatch(version.strip().lower().removeprefix("v"))
    if match is None:
        return False
    epoch, release_text, suffix = match.groups()
    if epoch and int(epoch) > 0:
        return False  # an epoch 1+ version sorts after every 2.x and 3.x
    parts = tuple(int(part) for part in release_text.split("."))
    width = max(len(parts), len(MIN_MCP_VERSION))
    release = parts + (0,) * (width - len(parts))  # "2.2" means 2.2.0
    floor = MIN_MCP_VERSION + (0,) * (width - len(MIN_MCP_VERSION))
    meets_floor = release > floor if _PRE_RELEASE.match(suffix) else release >= floor
    return meets_floor and release[0] < MCP_MAJOR_CEILING


def check_mcp_extra(_config: CliConfig) -> CheckResult:
    # Read package metadata only: importing mcp is slow and may fail on old versions.
    version = _installed_version("mcp")
    if version is None:
        return CheckResult("mcp_extra", True, "MCP extra is not installed; this is a CLI-only install.")
    if not _in_supported_range(version):
        supported = f">={'.'.join(map(str, MIN_MCP_VERSION))},<{MCP_MAJOR_CEILING}"
        return _failure(
            "mcp_extra",
            f"mcp {version} is installed; garmin-py supports mcp {supported}.",
            "INVALID_INPUT",
            "Reinstall the supported mcp version: pip install --upgrade 'garmin-py[mcp]'",
        )
    return CheckResult("mcp_extra", True, f"MCP extra is installed (mcp {version}).")


def check_session(config: CliConfig) -> CheckResult:
    probe = probe_session_status(config)
    detail = f"{probe.detail} Probe latency: {probe.latency_ms:.1f} ms."
    if probe.authenticated:
        return CheckResult("session", True, detail)
    if probe.error_code == "AUTH_MISSING" and _has_env_credentials(config):
        return CheckResult("session", True, f"{detail} {_ENV_CREDENTIALS}")
    return _failure("session", detail, probe.error_code or "AUTH_FAILED")


def check_write_surface(_config: CliConfig, read_only: bool | None = None) -> CheckResult:
    """``read_only`` is a running server's mode; None reads the environment."""
    problems: list[tuple[str, str]] = []  # (detail, hint); every problem is reported
    note = ""
    if read_only is None:
        raw = os.environ.get(READ_ONLY_ENV, "").strip().lower()
        if raw not in READ_ONLY_TRUE | READ_ONLY_FALSE:
            problems.append((
                f"{READ_ONLY_ENV} must be a boolean such as 1/0 or true/false.",
                f"Set {READ_ONLY_ENV} to 1 or true for a read-only server, or unset it.",
            ))
        read_only = raw in READ_ONLY_TRUE
        note = " (Read from the environment: a --read-only flag passed to a running server is not visible here.)"
    # The bind host is a per-invocation CLI flag with no config fallback, so
    # only the bearer-token state can be diagnosed ahead of time.
    # Present-but-blank is a misconfiguration (HTTP binds refuse to start),
    # not "unset".
    raw_token = os.environ.get(BEARER_ENV)
    if raw_token is not None:
        try:
            validate_bearer_token(raw_token)
        except ValueError as exc:
            problems.append((str(exc), f"Set {BEARER_ENV} to a valid token, or unset it for stdio-only use."))
    if problems:
        return _failure(
            "write_surface",
            " ".join(detail for detail, _ in problems),
            "INVALID_INPUT",
            " ".join(hint for _, hint in problems),
        )
    mode = (
        f"MCP server is read-only ({READ_ONLY_ENV} or --read-only): write tools are not registered."
        if read_only
        else "MCP write tools are enabled."
    ) + note
    detail = (
        f"{mode} Stdio is trusted; HTTP binds enforce the "
        f"bearer token ({BEARER_ENV}) whenever it is present, and non-loopback "
        "HTTP binds require it. "
        f"Bearer token configured: {str(raw_token is not None).lower()}."
    )
    return CheckResult("write_surface", True, detail)


_CHECKS: tuple[Callable[[CliConfig], CheckResult], ...] = (
    check_python_version,
    check_versions,
    check_config,
    check_token_store,
    check_legacy_garth,
    check_mcp_extra,
    check_session,
    check_write_surface,
)


def run_checks(
    config: CliConfig,
    *,
    fast: bool = False,
    include_mcp_extra: bool = True,
    read_only: bool | None = None,
) -> list[CheckResult]:
    """Run all requested checks, capturing every unexpected failure.

    ``read_only`` is passed to :func:`check_write_surface`.
    """
    results: list[CheckResult] = []
    for check in _CHECKS:
        if check is check_mcp_extra and not include_mcp_extra:
            continue
        if check is check_session and fast:
            results.append(CheckResult("session", True, "Skipped network probe (--fast)."))
            continue
        try:
            results.append(check_write_surface(config, read_only) if check is check_write_surface else check(config))
        except Exception:
            results.append(
                _failure(
                    check.__name__.removeprefix("check_"),
                    "The diagnostic check failed unexpectedly.",
                    "INTERNAL_ERROR",
                )
            )
    return results
