"""Authentication via the maintained Garmin backend."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date
from typing import Any

from garmin_cli import backend as garth
from garmin_cli._env import _env_float
from garmin_cli.config import CliConfig
from garmin_cli.exceptions import GarminCliError, extract_status_code
from garmin_cli.token_store import ensure_secure_directory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Probe-TTL cache
# ---------------------------------------------------------------------------

_DEFAULT_PROBE_TTL: float = 600.0

_probe_cache_lock: threading.Lock = threading.Lock()
# Map of garth_home -> timestamp of last successful probe (monotonic clock).
_last_probe_ok: dict[str, float] = {}
# The garth_home for which the backend is currently loaded.
_cached_garth_home: str | None = None


def _get_probe_ttl() -> float:
    """Return the probe TTL in seconds from the environment.

    ``GARMIN_CLI_AUTH_PROBE_TTL`` may be set to a non-negative float.
    ``0`` disables caching entirely (today's behaviour).  Invalid or
    negative values fall back to the 600 s default.
    """
    return _env_float("GARMIN_CLI_AUTH_PROBE_TTL", _DEFAULT_PROBE_TTL)


def _probe_cache_hit(garth_home: str, ttl: float) -> bool:
    """Return True when the cache entry is valid (TTL > 0 and not expired)."""
    if ttl == 0:
        return False
    with _probe_cache_lock:
        if _cached_garth_home != garth_home:
            return False
        last = _last_probe_ok.get(garth_home)
        if last is None:
            return False
        return (time.monotonic() - last) < ttl


def _record_probe_ok(garth_home: str) -> None:
    """Record a successful probe for *garth_home*."""
    with _probe_cache_lock:
        global _cached_garth_home
        _cached_garth_home = garth_home
        _last_probe_ok[garth_home] = time.monotonic()


def _invalidate_probe_cache(garth_home: str | None = None) -> None:
    """Invalidate cache entries.

    If *garth_home* is given, only that key is removed.  Otherwise the
    entire cache is cleared (used on login, which replaces any session).
    """
    with _probe_cache_lock:
        global _cached_garth_home
        if garth_home is not None:
            _last_probe_ok.pop(garth_home, None)
            if _cached_garth_home == garth_home:
                _cached_garth_home = None
        else:
            _last_probe_ok.clear()
            _cached_garth_home = None


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------


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

    On a probe-TTL cache hit the function returns immediately without any
    disk reads or network calls; the directory security check is deferred
    to the next cache miss so hot MCP servers skip the per-call stat/chmod.

    Raises:
        GarminCliError: With error_code AUTH_MISSING if no session and no credentials.
        GarminCliError: With error_code AUTH_FAILED if login fails or security check fails.
    """
    garth_home = os.path.expanduser(config.garth_home)

    ttl = _get_probe_ttl()
    if _probe_cache_hit(garth_home, ttl):
        logger.debug("Auth probe cache hit for %s — skipping resume+probe", garth_home)
        return

    _secure_directory(garth_home)

    try:
        garth.resume(garth_home)
        try:
            _probe_session()
            _record_probe_ok(garth_home)
            return
        except Exception as exc:
            _invalidate_probe_cache(garth_home)
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
    except Exception as exc:
        # Session expired/missing/corrupt — fall through to login. Broad by
        # design: garth/garminconnect exception shapes vary across versions, so
        # any resume failure should re-auth rather than crash. Logged for triage.
        _invalidate_probe_cache(garth_home)
        logger.debug("Garmin session resume failed, falling through to login: %s", exc)

    if not config.email or not config.password:
        raise GarminCliError(
            error=(
                "No usable saved session found and GARMIN_EMAIL / GARMIN_PASSWORD "
                "are not set. Set these credentials to authenticate."
            ),
            error_code="AUTH_MISSING",
        )

    try:
        _invalidate_probe_cache()  # login replaces the session entirely
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
