"""Non-raising environment and session diagnostics."""
from __future__ import annotations

import importlib.util
import os
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from garmin_cli.auth import probe_session_status
from garmin_cli.config import CliConfig
from garmin_cli.error_contracts import error_contract
from garmin_cli.bearer_token import BEARER_ENV, validate_bearer_token
from garmin_cli.exceptions import GarminCliError
from garmin_cli.token_store import (
    TOKEN_FILE_NAME,
    detect_legacy_tokens,
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


def _failure(name: str, detail: str, error_code: str) -> CheckResult:
    return CheckResult(
        name=name,
        ok=False,
        detail=detail,
        error_code=error_code,
        recovery_hint=error_contract(error_code)["recovery_hint"],
    )


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
    )


def check_config(config: CliConfig) -> CheckResult:
    path = Path(os.path.expanduser(config.garth_home))
    shown = _display_path(path)
    try:
        validate_garmin_home(str(path))
    except GarminCliError as exc:
        return _failure("config", exc.error, exc.error_code)  # names the offending link
    if not path.exists():
        return _failure(
            "config",
            f"Garmin home {shown} does not exist.",
            "AUTH_MISSING",
        )
    return CheckResult("config", True, f"Garmin home resolves to {shown}.")


def check_token_store(config: CliConfig) -> CheckResult:
    path = Path(os.path.expanduser(config.garth_home))
    try:
        return _check_token_store(path)
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
        if detect_legacy_tokens(str(path)):
            return _failure(
                "token_store",
                f"Legacy Garmin session files were found in {shown}; log in again.",
                "AUTH_MISSING",
            )
        return _failure(
            "token_store",
            f"No token store was found in {shown}.",
            "AUTH_MISSING",
        )
    if stat.S_ISLNK(token_stat.st_mode):
        return _failure("token_store", f"Token file {TOKEN_FILE_NAME} is a symlink.", "AUTH_FAILED")
    if not stat.S_ISREG(token_stat.st_mode):
        return _failure(
            "token_store", f"Token file {TOKEN_FILE_NAME} is not a regular file.", "AUTH_FAILED"
        )
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o700:
        return _failure(
            "token_store",
            f"Token-store directory permissions are {mode:04o}; expected 0700.",
            "AUTH_FAILED",
        )
    file_mode = stat.S_IMODE(token_stat.st_mode)
    if file_mode != 0o600:
        return CheckResult(
            "token_store",
            False,
            f"Token file {TOKEN_FILE_NAME} permissions are {file_mode:04o}; expected 0600.",
            "AUTH_FAILED",
            f"Restrict {TOKEN_FILE_NAME} to owner read/write (mode 600).",
        )
    return CheckResult(
        "token_store", True, "Token store is present with 0700 directory and 0600 file permissions."
    )


def check_mcp_extra(_config: CliConfig) -> CheckResult:
    available = importlib.util.find_spec("mcp") is not None
    detail = "MCP extra is installed." if available else "MCP extra is not installed; this is a CLI-only install."
    return CheckResult("mcp_extra", True, detail)


def check_session(config: CliConfig) -> CheckResult:
    probe = probe_session_status(config)
    detail = f"{probe.detail} Probe latency: {probe.latency_ms:.1f} ms."
    if probe.authenticated:
        return CheckResult("session", True, detail)
    return _failure("session", detail, probe.error_code or "AUTH_FAILED")


def check_write_surface(_config: CliConfig) -> CheckResult:
    # The bind host is a per-invocation CLI flag with no config fallback, so
    # only the bearer-token state can be diagnosed ahead of time.
    # Present-but-blank is a misconfiguration (HTTP binds refuse to start),
    # not "unset".
    raw_token = os.environ.get(BEARER_ENV)
    if raw_token is not None:
        try:
            validate_bearer_token(raw_token)
        except ValueError as exc:
            return _failure("write_surface", str(exc), "INVALID_INPUT")
    detail = (
        "MCP write tools are enabled. Stdio is trusted; HTTP binds enforce the "
        f"bearer token ({BEARER_ENV}) whenever it is present, and non-loopback "
        "HTTP binds require it. "
        f"Bearer token configured: {str(raw_token is not None).lower()}."
    )
    return CheckResult("write_surface", True, detail)


_CHECKS: tuple[Callable[[CliConfig], CheckResult], ...] = (
    check_python_version,
    check_config,
    check_token_store,
    check_mcp_extra,
    check_session,
    check_write_surface,
)


def run_checks(
    config: CliConfig,
    *,
    fast: bool = False,
    include_mcp_extra: bool = True,
) -> list[CheckResult]:
    """Run all requested checks, capturing every unexpected failure."""
    results: list[CheckResult] = []
    for check in _CHECKS:
        if check is check_mcp_extra and not include_mcp_extra:
            continue
        if check is check_session and fast:
            results.append(CheckResult("session", True, "Skipped network probe (--fast)."))
            continue
        try:
            results.append(check(config))
        except Exception:
            results.append(
                _failure(
                    check.__name__.removeprefix("check_"),
                    "The diagnostic check failed unexpectedly.",
                    "INTERNAL_ERROR",
                )
            )
    return results
