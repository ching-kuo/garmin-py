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
from garmin_cli.backend import PendingMFA
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
# Pending-MFA state
# ---------------------------------------------------------------------------

# One pending login at a time: a new MFA challenge replaces any earlier one,
# matching the single-account model of the rest of the backend.
_pending_mfa_lock: threading.Lock = threading.Lock()
_pending_mfa: PendingMFA | None = None

# Serializes every authentication transition (credential login and MFA
# completion) so concurrent tool calls cannot start competing logins — each
# Garmin login on an MFA account sends the user a fresh one-time code and
# invalidates the previous challenge.
_login_lock: threading.Lock = threading.Lock()

_MFA_REQUIRED_MESSAGE = (
    "MFA_REQUIRED: Garmin requires a multi-factor authentication code to finish "
    "logging in. Ask the user for the one-time code Garmin just sent them, then "
    "submit it with the submit_mfa_code MCP tool (or run 'garmin-cli login' in a "
    "terminal)."
)


def _stash_pending_mfa(pending: PendingMFA | None) -> None:
    global _pending_mfa
    with _pending_mfa_lock:
        _pending_mfa = pending


def _take_pending_mfa() -> PendingMFA | None:
    global _pending_mfa
    with _pending_mfa_lock:
        pending, _pending_mfa = _pending_mfa, None
        return pending


def complete_mfa_login(config: CliConfig, mfa_code: str) -> None:
    """Finish a login that :func:`ensure_authenticated` left pending on MFA.

    Consumes the pending state either way: Garmin MFA challenges are
    single-use, so a wrong code requires restarting the login (any
    authenticated call re-triggers it and sends a fresh code).

    Raises:
        GarminCliError: INVALID_INPUT when no login is awaiting a code;
            RATE_LIMITED on a Garmin 429; AUTH_FAILED when Garmin rejects
            the code or the verified session cannot be persisted.
    """
    with _login_lock:
        pending = _take_pending_mfa()
        if pending is None:
            raise GarminCliError(
                error=(
                    "No Garmin login is awaiting an MFA code. Retry the original "
                    "request first; when it reports MFA_REQUIRED, submit the code."
                ),
                error_code="INVALID_INPUT",
            )
        garth_home = pending.garth_home or os.path.expanduser(config.garth_home)
        try:
            # Local precondition: a repairable path/permission problem must not
            # burn the still-valid challenge.
            _secure_directory(garth_home)
        except GarminCliError:
            _stash_pending_mfa(pending)
            raise
        try:
            garth.resume_mfa_login(pending, mfa_code)
        except Exception as exc:
            if extract_status_code(exc) == 429:
                # Throttled, not rejected — the challenge may still be valid.
                _stash_pending_mfa(pending)
            _raise_if_rate_limited(exc)
            raise GarminCliError(
                error=(
                    "MFA verification failed. Retry the original request to "
                    "receive a fresh code, then submit it again."
                ),
                error_code="AUTH_FAILED",
            ) from exc
        _persist_session(garth_home)
        _record_probe_ok(garth_home)


def _raise_if_rate_limited(exc: Exception) -> None:
    """Map a Garmin 429 to RATE_LIMITED; return for the caller's own mapping otherwise."""
    if extract_status_code(exc) == 429:
        raise GarminCliError(
            error="Garmin login is temporarily rate limited. Try again shortly.",
            error_code="RATE_LIMITED",
        ) from exc


def _persist_session(garth_home: str) -> None:
    """Save the active backend session, reporting persistence failures as such."""
    try:
        os.makedirs(garth_home, mode=0o700, exist_ok=True)
        garth.save(garth_home)
    except Exception as exc:
        raise GarminCliError(
            error=f"Authenticated, but saving the session to {garth_home} failed: {exc}",
            error_code="AUTH_FAILED",
        ) from exc


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
            # A working session makes any outstanding MFA challenge moot;
            # drop it so the half-authenticated client is released.
            _stash_pending_mfa(None)
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

    with _login_lock:
        # A challenge is already outstanding (possibly stashed by a concurrent
        # call while we waited for the lock): re-raise instead of starting
        # another login, which would send the user a fresh code and invalidate
        # the one they are about to submit.
        if _pending_mfa is not None:
            raise GarminCliError(error=_MFA_REQUIRED_MESSAGE, error_code="MFA_REQUIRED")

        _invalidate_probe_cache()  # login replaces the session entirely
        try:
            pending = garth.login(
                config.email,
                config.password,
                garth_home=garth_home,
                return_on_mfa=True,
            )
        except Exception as exc:
            _raise_if_rate_limited(exc)
            raise GarminCliError(
                error="Authentication failed. Check your credentials.",
                error_code="AUTH_FAILED",
            ) from exc
        if isinstance(pending, PendingMFA):
            _stash_pending_mfa(pending)
            raise GarminCliError(error=_MFA_REQUIRED_MESSAGE, error_code="MFA_REQUIRED")
        _persist_session(garth_home)
