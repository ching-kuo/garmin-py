"""Token store helpers for the Garmin backend."""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

DEFAULT_GARMIN_HOME = "~/.garminconnect"
LEGACY_GARTH_HOME = "~/.garth"


LEGACY_TOKEN_FILES = frozenset({
    "oauth1_token.json",
    "oauth2_token.json",
    "oauth_token.json",
    "garth_session.token",
})


def expand_garth_home(path: str) -> Path:
    """Return the expanded GARTH_HOME directory path."""
    return Path(os.path.expanduser(path))


def ensure_secure_directory(path: str, *, create: bool = False) -> Path:
    """Secure the directory, then migrate the legacy default tokenstore if needed."""
    directory = expand_garth_home(path)

    if directory.is_symlink():
        raise OSError(f"garth_home path '{directory}' is a symlink")

    migrate_legacy_default_tokenstore(path)

    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    if directory.exists():
        current_mode = stat.S_IMODE(directory.stat().st_mode)
        if current_mode != 0o700:
            os.chmod(directory, 0o700)

    return directory


def tokenstore_path(path: str) -> Path:
    """Return the canonical `garmin_tokens.json` file path for GARTH_HOME."""
    base = expand_garth_home(path)
    if base.suffix == ".json":
        return base
    return base / "garmin_tokens.json"


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


def migrate_legacy_default_tokenstore(path: str) -> None:
    """Copy `~/.garth/garmin_tokens.json` into the new default home on first use."""
    target_directory = expand_garth_home(path)
    if target_directory != expand_garth_home(DEFAULT_GARMIN_HOME):
        return

    target_token_file = tokenstore_path(str(target_directory))
    if target_token_file.exists():
        return

    legacy_token_file = tokenstore_path(LEGACY_GARTH_HOME)
    if not legacy_token_file.exists():
        return

    target_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copy2(legacy_token_file, target_token_file)
    secure_token_file(str(target_directory))
