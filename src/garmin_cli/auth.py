"""Authentication via the maintained Garmin backend."""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

from garmin_cli import backend as garth
from garmin_cli.config import CliConfig
from garmin_cli.endpoints._base import extract_status_code
from garmin_cli.exceptions import GarminCliError
from garmin_cli.token_store import ensure_secure_directory

logger = logging.getLogger(__name__)


def _secure_directory(path: str) -> None:
    """Ensure path is not a symlink and has owner-only permissions.

    Raises GarminCliError if the path is a symlink or if permission
    repair fails.
    """
    try:
        ensure_secure_directory(path)
    except OSError as exc:
        if os.path.islink(path):
            raise GarminCliError(
                error=f"garmin_home path '{path}' is a symlink — refusing for security",
                error_code="AUTH_FAILED",
            ) from exc
        raise GarminCliError(
            error=(
                f"garmin_home directory has insecure permissions "
                f"and cannot be repaired: {exc}"
            ),
            error_code="AUTH_FAILED",
        ) from exc


def _probe_session(garth_client: Any | None = None) -> None:
    """Verify that resumed tokens still authorize a simple Garmin request.

    garth_client defaults to the module-level garth so callers can pass
    their own patched instance in tests without also patching auth.garth.
    """
    if garth_client is None:
        garth_client = garth
    today = date.today()
    garth_client.connectapi(
        f"/calendar-service/year/{today.year}/month/{today.month - 1}/day/{today.day}/start/1"
    )


def ensure_authenticated(config: CliConfig) -> None:
    """Authenticate with Garmin Connect.

    Tries to resume an existing session. If that fails and credentials
    are available, performs a fresh login and saves the session.

    Raises:
        GarminCliError: With error_code AUTH_MISSING if no session and no credentials.
        GarminCliError: With error_code AUTH_FAILED if login fails or security check fails.
    """
    garth_home = os.path.expanduser(config.garth_home)

    _secure_directory(garth_home)

    try:
        garth.resume(garth_home)
        try:
            _probe_session()
            return
        except Exception as exc:
            if extract_status_code(exc) not in (401, 403):
                raise GarminCliError(
                    error="Saved Garmin session could not be validated.",
                    error_code="AUTH_FAILED",
                ) from exc
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise GarminCliError(
            error=f"Cannot access session directory: {exc}",
            error_code="AUTH_FAILED",
        ) from exc
    except GarminCliError:
        raise
    except Exception:
        pass  # session expired or missing — fall through to login

    if not config.email or not config.password:
        raise GarminCliError(
            error=(
                "No usable saved session found and GARMIN_EMAIL / GARMIN_PASSWORD "
                "are not set. Set these credentials to authenticate."
            ),
            error_code="AUTH_MISSING",
        )

    try:
        garth.login(config.email, config.password, garth_home=garth_home)
        os.makedirs(garth_home, mode=0o700, exist_ok=True)
        garth.save(garth_home)
    except Exception as exc:
        if extract_status_code(exc) == 429:
            logger.debug("Garmin login hit rate limiting for %s", garth_home)
            raise GarminCliError(
                error="Garmin login is temporarily rate limited. Try again shortly.",
                error_code="RATE_LIMITED",
            ) from exc
        raise GarminCliError(
            error="Authentication failed. Check your credentials.",
            error_code="AUTH_FAILED",
        ) from exc
