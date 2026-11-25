"""Authentication via the maintained Garmin backend."""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from garmin_cli import backend as garth
from garmin_cli import login_backoff
from garmin_cli._env import _env_float
from garmin_cli.backend import PendingMFA
from garmin_cli.config import CliConfig
from garmin_cli.exceptions import GarminCliError, extract_status_code
from garmin_cli.token_store import ensure_secure_directory, expand_garth_home

logger = logging.getLogger(__name__)

# --- Probe-TTL cache --------------------------------------------------------

_DEFAULT_PROBE_TTL: float = 600.0

_probe_cache_lock: threading.Lock = threading.Lock()
# Map of garth_home -> timestamp of last successful probe (monotonic clock).
_last_probe_ok: dict[str, float] = {}
# The garth_home for which the backend is currently loaded.
_cached_garth_home: str | None = None


@dataclass(frozen=True)
class SessionProbeResult:
    """Non-raising status from validating a saved Garmin session."""

    authenticated: bool
    garmin_home: str
    latency_ms: float
    error_code: str | None = None
    detail: str = ""


def _home_key(path: str) -> str:
    """One spelling per Garmin home (no trailing slash) for every per-home cache."""
    return str(expand_garth_home(path))


def _get_probe_ttl() -> float:
    """``GARMIN_CLI_AUTH_PROBE_TTL`` seconds (0 disables; invalid/negative -> 600)."""
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
    """Drop *garth_home*'s entry, or everything (login replaces any session)."""
    with _probe_cache_lock:
        global _cached_garth_home
        if garth_home is not None:
            _last_probe_ok.pop(garth_home, None)
            if _cached_garth_home == garth_home:
                _cached_garth_home = None
        else:
            _last_probe_ok.clear()
            _cached_garth_home = None


# --- Pending-MFA state ------------------------------------------------------

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


def _has_pending_mfa() -> bool:
    with _pending_mfa_lock:
        return _pending_mfa is not None


def _login_error(
    exc: Exception, rejected: str = "Authentication failed. Check your credentials."
) -> GarminCliError:
    """Map a failed login/MFA step; only *rejected* failures blame the credentials."""
    kind = login_backoff.failure_kind(exc)
    if kind == "throttled":
        return GarminCliError(
            error="Garmin login is temporarily rate limited. Try again shortly.",
            error_code="RATE_LIMITED",
        )
    if kind == "rejected":
        return GarminCliError(error=rejected, error_code="AUTH_FAILED")
    if kind == "server":
        return GarminCliError(
            error="Garmin returned a server error during login. Try again later.",
            error_code="SERVER_ERROR",
        )
    return GarminCliError(
        error="Could not reach Garmin to log in. Check connectivity and try again.",
        error_code="AUTH_FAILED",
    )


def complete_mfa_login(config: CliConfig, mfa_code: str) -> None:
    """Finish a login that :func:`ensure_authenticated` left pending on MFA.

    Consumes the pending state either way: Garmin MFA challenges are
    single-use, so a wrong code requires restarting the login (any
    authenticated call re-triggers it and sends a fresh code).

    Raises:
        GarminCliError: INVALID_INPUT when no login is awaiting a code;
            RATE_LIMITED when throttled (challenge kept); AUTH_FAILED when Garmin
            rejects the code, is unreachable, or the session cannot be persisted.
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
        garth_home = _home_key(pending.garth_home or config.garth_home)
        try:
            # Local preconditions (a repairable path problem, a backoff window
            # after a 429) must not burn the still-valid challenge.
            login_backoff.raise_if_backing_off(config)
            _secure_directory(garth_home)
        except GarminCliError:
            _stash_pending_mfa(pending)
            raise
        try:
            client = garth.resume_mfa_login(pending, mfa_code)
        except Exception as exc:
            error = _login_error(
                exc,
                "MFA verification failed. Retry the original request to "
                "receive a fresh code, then submit it again.",
            )
            if error.error_code == "RATE_LIMITED":
                # Throttled, not rejected — the challenge may still be valid.
                _stash_pending_mfa(pending)
            # Back off so the next call does not instantly send another code.
            raise login_backoff.record_if_counted(config, exc, error, mfa=True) from exc
        _persist_session(garth_home, client)
        login_backoff.record_success(garth_home)
        _record_probe_ok(garth_home)


def _persist_session(garth_home: str, client: Any) -> None:
    """Save and publish a freshly authenticated client, reporting persistence failures."""
    try:
        os.makedirs(garth_home, mode=0o700, exist_ok=True)
        garth.save(garth_home, client)
    except Exception as exc:
        raise GarminCliError(
            error=f"Authenticated, but saving the session to {garth_home} failed: {exc}",
            error_code="AUTH_FAILED",
        ) from exc


def _secure_directory(path: str) -> None:
    """Validate *path* (symlinks, non-directory) and repair it to owner-only mode."""
    try:
        ensure_secure_directory(path)
    except OSError as exc:
        raise GarminCliError(
            error=f"garmin_home directory has insecure permissions and cannot be repaired: {exc}",
            error_code="AUTH_FAILED",
        ) from exc


def _probe_session(garth_client: Any | None = None) -> None:
    """Verify resumed tokens still authorize a request (callers may pass their patched garth)."""
    if garth_client is None:
        garth_client = garth
    today = date.today()
    garth_client.connectapi(
        f"/calendar-service/year/{today.year}/month/{today.month - 1}/day/{today.day}/start/1"
    )


def probe_session_status(config: CliConfig) -> SessionProbeResult:
    """Resume and validate the saved session without ever raising.

    This is a read-only surface (doctor, login_status, resources): it reports
    problems without repairing directory permissions or migrating legacy
    tokens — those side effects belong to :func:`ensure_authenticated`.

    Error details are intentionally generic: callers may print this result and
    must not leak upstream response bodies, account identifiers, or tokens.
    """
    garmin_home = os.path.expanduser(config.garth_home)
    started = time.monotonic()
    authenticated = False
    error_code: str | None = None
    detail = "Saved Garmin session is unavailable."
    try:
        garth.resume(garmin_home, read_only=True)  # validates the home first
        _probe_session()
        authenticated = True
        detail = "Saved Garmin session is valid."
    except FileNotFoundError:
        error_code = "AUTH_MISSING"
        detail = "No saved Garmin session was found."
    except OSError:
        error_code = "AUTH_FAILED"
        detail = "The Garmin session directory cannot be accessed."
    except GarminCliError as exc:
        error_code = exc.error_code
        detail = (
            "The Garmin session path is not usable."
            if exc.error_code in ("AUTH_FAILED", "INVALID_INPUT")
            else "The saved Garmin session could not be validated."
        )
    except Exception as exc:
        status = extract_status_code(exc)
        error_code = "AUTH_FAILED"
        detail = (
            "The saved Garmin session was rejected."
            if status in (401, 403)
            else "The saved Garmin session could not be validated."
        )
    return SessionProbeResult(
        authenticated=authenticated,
        garmin_home=garmin_home,
        latency_ms=round((time.monotonic() - started) * 1000, 1),
        error_code=error_code,
        detail=detail,
    )


def ensure_authenticated(config: CliConfig) -> None:
    """Resume the saved session, else log in with credentials and save it.

    A probe-TTL cache hit returns with no disk or network I/O; the directory
    security check waits for the next miss so hot MCP servers skip stat/chmod.

    Raises:
        GarminCliError: AUTH_MISSING with no session and no credentials;
            AUTH_FAILED / RATE_LIMITED / SERVER_ERROR when login fails (the
            cached error with ``retry_after_seconds`` while logins are paused).
    """
    garth_home = _home_key(config.garth_home)
    generation = login_backoff.generation(garth_home)

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
            login_backoff.clear()
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
                "No saved Garmin session found. Run `garmin-cli login` to sign in, "
                "or set GARMIN_EMAIL and GARMIN_PASSWORD."
            ),
            error_code="AUTH_MISSING",
        )

    with _login_lock:
        # A peer logged this home in while we waited. Re-resume from what it
        # persisted rather than trusting the live backend, which a concurrent
        # stale resume may have replaced; log in ourselves if that fails.
        if login_backoff.generation(garth_home) != generation and _resumed_session_works(
            garth_home
        ):
            return
        # A challenge is already outstanding (possibly stashed by a concurrent
        # call while we waited for the lock): re-raise instead of starting
        # another login, which would send the user a fresh code and invalidate
        # the one they are about to submit.
        if _has_pending_mfa():
            raise GarminCliError(error=_MFA_REQUIRED_MESSAGE, error_code="MFA_REQUIRED")
        login_backoff.raise_if_backing_off(config)

        _invalidate_probe_cache()  # login replaces the session entirely
        try:
            result = garth.login(
                config.email,
                config.password,
                garth_home=garth_home,
                return_on_mfa=True,
            )
        except Exception as exc:
            raise login_backoff.record_if_counted(config, exc, _login_error(exc)) from exc
        if isinstance(result, PendingMFA):
            _stash_pending_mfa(result)
            raise GarminCliError(error=_MFA_REQUIRED_MESSAGE, error_code="MFA_REQUIRED")
        _persist_session(garth_home, result)
        login_backoff.record_success(garth_home)


def _resumed_session_works(garth_home: str) -> bool:
    """Resume *garth_home* from disk and probe it; True (and cached) on success.

    False only when nothing resumes or the saved session is rejected (401/403);
    any other probe failure is reported like the primary resume path.
    """
    try:
        garth.resume(garth_home)
    except Exception:
        return False
    try:
        _probe_session()
    except Exception as exc:
        if extract_status_code(exc) in (401, 403):
            return False
        raise GarminCliError(
            error="Saved Garmin session could not be validated.", error_code="AUTH_FAILED"
        ) from exc
    _record_probe_ok(garth_home)
    return True
