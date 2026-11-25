"""In-process failed-login backoff and per-home login generations.

Repeated SSO attempts with bad credentials risk an account lockout and, on MFA
accounts, spam the user with one-time codes. State is guarded by
``auth._login_lock`` (callers hold it for every read-modify-write); ``clear``
is a single assignment, safe to call without it.
"""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass

from garmin_cli.config import CliConfig
from garmin_cli.exceptions import GarminCliError, failure_kind

BACKOFF_START: float = 60.0
BACKOFF_CAP: float = 900.0


_MFA_REJECTED = (
    "The MFA code was rejected. Wait {seconds} seconds, then retry the original "
    "request to have Garmin send a new code."
)


@dataclass(frozen=True)
class _Failure:
    credentials: str  # digest of email+password: a credential change resets backoff
    error: str
    error_code: str
    at: float
    count: int
    mfa_rejected: bool = False

    @property
    def backoff(self) -> float:
        return min(BACKOFF_START * 2 ** min(self.count - 1, 10), BACKOFF_CAP)

    def message(self, seconds: int) -> str:
        if self.mfa_rejected:
            return _MFA_REJECTED.format(seconds=seconds)
        return (
            f"{self.error} New Garmin login attempts are paused after a failed "
            f"login; retry after {seconds} seconds."
        )


_failure: _Failure | None = None
# garmin_home -> count of successful logins, so a caller that waited on the
# login lock can tell a peer authenticated the same home meanwhile.
_generations: dict[str, int] = {}


def _credential_key(config: CliConfig) -> str:
    return hashlib.sha256(f"{config.email}\0{config.password}".encode()).hexdigest()


def record_failure(
    config: CliConfig, error: GarminCliError, *, mfa: bool = False
) -> GarminCliError:
    """Start or extend the backoff; return *error* rebuilt with the wait it started.

    ``mfa=True`` marks a failed MFA submission: a rejected code gets a message
    that says how long to wait before asking Garmin for a new one.
    """
    global _failure
    key = _credential_key(config)
    previous = _failure
    count = previous.count + 1 if previous is not None and previous.credentials == key else 1
    _failure = _Failure(
        key, error.error, error.error_code, time.monotonic(), count,
        mfa_rejected=mfa and error.error_code == "AUTH_FAILED",
    )
    wait = math.ceil(_failure.backoff)
    return GarminCliError(
        error=_MFA_REJECTED.format(seconds=wait) if _failure.mfa_rejected else error.error,
        error_code=error.error_code,
        retry_after_seconds=wait,
    )


def record_if_counted(
    config: CliConfig, exc: Exception, error: GarminCliError, *, mfa: bool = False
) -> GarminCliError:
    """Start the backoff only for credential rejections and throttles.

    Network errors, timeouts and 5xx say nothing about the credentials, so
    they return *error* unchanged and never pause logins.
    """
    if failure_kind(exc, login=True) in ("throttled", "rejected"):
        return record_failure(config, error, mfa=mfa)
    return error


def clear() -> None:
    global _failure
    _failure = None


def raise_if_backing_off(config: CliConfig) -> None:
    """Re-raise the cached failure while its backoff window is open."""
    failure = _failure
    if failure is None or failure.credentials != _credential_key(config):
        return
    remaining = math.ceil(failure.at + failure.backoff - time.monotonic())
    if remaining > 0:
        raise GarminCliError(
            error=failure.message(remaining),
            error_code=failure.error_code,
            retry_after_seconds=remaining,
        )


def generation(garmin_home: str) -> int:
    return _generations.get(garmin_home, 0)


def record_success(garmin_home: str) -> None:
    clear()
    _generations[garmin_home] = generation(garmin_home) + 1
