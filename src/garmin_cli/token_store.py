"""Token store helpers for the Garmin backend."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from garmin_cli.exceptions import GarminCliError

DEFAULT_GARMIN_HOME = "~/.garminconnect"
TOKEN_FILE_NAME = "garmin_tokens.json"


def expand_garmin_home(path: str) -> Path:
    """Return the expanded Garmin home directory path."""
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
    directory = expand_garmin_home(path)
    link = _symlinked_component(directory)
    if link is not None:
        raise GarminCliError(
            error=f"garmin_home path '{directory}' passes through symlink '{link}' — refusing for security",
            error_code="AUTH_FAILED",
            local_config=True,
        )
    if directory.suffix.casefold() == ".json" or (directory.exists() and not directory.is_dir()):
        raise GarminCliError(
            error=f"GARMIN_HOME must be a directory: '{directory}'",
            error_code="INVALID_INPUT",
        )
    return directory


def ensure_secure_directory(path: str, *, create: bool = False) -> Path:
    """Validate the Garmin home, optionally create it, and restrict it to mode 0700."""
    directory = validate_garmin_home(path)

    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    if directory.exists():
        current_mode = stat.S_IMODE(directory.stat().st_mode)
        if current_mode != 0o700:
            os.chmod(directory, 0o700)

    return directory


def tokenstore_path(path: str) -> Path:
    """Return the canonical `garmin_tokens.json` file path for the Garmin home."""
    return expand_garmin_home(path) / TOKEN_FILE_NAME


def token_file_identity(path: str) -> tuple[int, int, int] | None:
    """``(mtime_ns, size, inode)`` of the token file, or None when absent.

    Metadata only, never the contents: a login or logout in any process
    changes it, so per-process session caches can tell they are stale.
    """
    try:
        info = os.stat(tokenstore_path(path), follow_symlinks=False)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size, info.st_ino)


def has_tokenstore(path: str) -> bool:
    """Return True when garmin_tokens.json exists in the Garmin home."""
    return tokenstore_path(path).exists()


def secure_token_file(path: str) -> Path:
    """Enforce owner-only permissions on the persisted token file."""
    token_file = tokenstore_path(path)
    if token_file.is_symlink():
        raise OSError(f"Token file '{token_file}' is a symlink — refusing for security")
    if token_file.exists():
        os.chmod(token_file, 0o600)
    return token_file
