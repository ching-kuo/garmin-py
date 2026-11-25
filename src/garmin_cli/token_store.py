"""Token store helpers for the Garmin backend."""
from __future__ import annotations

import errno
import logging
import os
import secrets
import stat
from pathlib import Path

from garmin_cli.exceptions import GarminCliError

logger = logging.getLogger(__name__)

DEFAULT_GARMIN_HOME = "~/.garminconnect"
LEGACY_GARTH_HOME = "~/.garth"
TOKEN_FILE_NAME = "garmin_tokens.json"


LEGACY_TOKEN_FILES = frozenset({
    "oauth1_token.json",
    "oauth2_token.json",
    "oauth_token.json",
    "garth_session.token",
})


def expand_garth_home(path: str) -> Path:
    """Return the expanded GARTH_HOME directory path."""
    return Path(os.path.expanduser(path))


def _symlinked_component(directory: Path) -> Path | None:
    """Return the first symlink in *directory* or its parents, if any.

    Root-owned links (macOS ``/tmp`` and ``/var``, Fedora Silverblue's
    ``/home``) can only be planted by root, so they are allowed on POSIX,
    mirroring garminconnect's own token-path check.
    """
    absolute = directory.absolute()
    for component in (absolute, *absolute.parents):
        if component.is_symlink() and not (
            os.name == "posix" and os.lstat(component).st_uid == 0
        ):
            return component
    return None


def validate_garmin_home(path: str) -> Path:
    """Read-only checks shared by every surface that touches the Garmin home.

    Raises:
        GarminCliError: AUTH_FAILED when a path component is a symlink;
            INVALID_INPUT when the path is a ``.json`` file path or an existing
            non-directory.
    """
    directory = expand_garth_home(path)
    link = _symlinked_component(directory)
    if link is not None:
        raise GarminCliError(
            error=f"garmin_home path '{directory}' passes through symlink '{link}' — refusing for security",
            error_code="AUTH_FAILED",
        )
    if directory.suffix.casefold() == ".json" or (directory.exists() and not directory.is_dir()):
        raise GarminCliError(
            error=f"GARMIN_HOME must be a directory: '{directory}'",
            error_code="INVALID_INPUT",
        )
    return directory


def ensure_secure_directory(path: str, *, create: bool = False) -> Path:
    """Secure the directory, then migrate the legacy default tokenstore if needed."""
    directory = validate_garmin_home(path)

    try:
        migrate_legacy_default_tokenstore(path)
    except OSError as exc:  # best-effort copy: never block authentication on it
        logger.debug("Legacy token migration skipped: %s", type(exc).__name__)

    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    if directory.exists():
        current_mode = stat.S_IMODE(directory.stat().st_mode)
        if current_mode != 0o700:
            os.chmod(directory, 0o700)

    return directory


def tokenstore_path(path: str) -> Path:
    """Return the canonical `garmin_tokens.json` file path for GARTH_HOME."""
    return expand_garth_home(path) / TOKEN_FILE_NAME


def has_tokenstore(path: str) -> bool:
    """Return True when the new tokenstore exists."""
    return tokenstore_path(path).exists()


def detect_legacy_tokens(path: str) -> list[str]:
    """List legacy garth token files present in GARTH_HOME."""
    directory = expand_garth_home(path)
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(name for name in LEGACY_TOKEN_FILES if (directory / name).exists())


def secure_token_file(path: str) -> Path:
    """Enforce owner-only permissions on the persisted token file."""
    token_file = tokenstore_path(path)
    if token_file.is_symlink():
        raise OSError(f"Token file '{token_file}' is a symlink — refusing for security")
    if token_file.exists():
        os.chmod(token_file, 0o600)
    return token_file


def legacy_tokenstore_path() -> Path | None:
    """`~/.garth/garmin_tokens.json`, or None when ~/.garth is not a real directory
    or the token file is a symlink (both are ignored, never followed)."""
    legacy_home = expand_garth_home(LEGACY_GARTH_HOME)
    token_file = legacy_home / TOKEN_FILE_NAME
    if legacy_home.is_symlink() or not legacy_home.is_dir() or token_file.is_symlink():
        return None
    return token_file


def _read_legacy_token() -> bytes | None:
    """Return the legacy default token bytes, or None if absent or unsafe to read."""
    # shortcut: lstat checks the legacy directory, so a swap of ~/.garth between
    # check and open is not covered; O_NOFOLLOW covers the file itself.
    legacy_token_file = legacy_tokenstore_path()
    if legacy_token_file is None:
        return None
    # O_NONBLOCK: opening a planted FIFO must not hang authentication.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(legacy_token_file, flags)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:  # O_NOFOLLOW hit a symlink swapped in meanwhile
            return None
        raise
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    with os.fdopen(fd, "rb") as source:
        return source.read()


def _create_owner_only(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(payload)


def migrate_legacy_default_tokenstore(path: str) -> None:
    """Copy `~/.garth/garmin_tokens.json` into the new default home on first use."""
    target_directory = expand_garth_home(path)
    if target_directory != expand_garth_home(DEFAULT_GARMIN_HOME):
        return

    target_token_file = tokenstore_path(str(target_directory))
    if os.path.lexists(target_token_file):
        return

    payload = _read_legacy_token()
    if payload is None:
        return

    target_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Created 0600 from the start (never briefly umask-readable), then linked
    # into place only if no token appeared meanwhile: a concurrent login wins.
    tmp = target_token_file.with_name(f".{TOKEN_FILE_NAME}.{secrets.token_hex(8)}.tmp")
    try:
        _create_owner_only(tmp, payload)
        try:
            os.link(tmp, target_token_file)
        except FileExistsError:
            pass
        except OSError:  # filesystem without hard links
            try:
                _create_owner_only(target_token_file, payload)
            except FileExistsError:
                pass
    finally:
        tmp.unlink(missing_ok=True)
