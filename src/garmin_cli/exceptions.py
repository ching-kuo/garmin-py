"""Custom exceptions for garmin-cli and classification of upstream failures."""
from __future__ import annotations

import functools
import re
from typing import Any, Literal, NamedTuple


class GarminCliError(Exception):
    """Raised for all expected garmin-cli failures.

    Attributes:
        error: Human-readable error message.
        error_code: Machine-readable error code (e.g. AUTH_FAILED, NOT_FOUND).
        retry_after_seconds: Known wait before a retry can succeed, if any.
        may_have_landed: An earlier attempt of this request failed in a way
            Garmin may still have applied (5xx, read timeout), whatever the
            final error says.
    """

    def __init__(
        self,
        error: str,
        error_code: str,
        *,
        retry_after_seconds: int | None = None,
        may_have_landed: bool = False,
    ) -> None:
        self.error = error
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds
        self.may_have_landed = may_have_landed
        super().__init__(error)


# Only explicit HTTP status wording ("API Error 503", "HTTP Error 503:",
# "API Error (429)", "client error (422)", "HTTP 503", "status code 503",
# "503 Server Error"), so "port=443", ".../workout/502" or "ride (429).fit"
# never match.
_STATUS_RE = re.compile(
    r"\b(?:client|server|api|http) error\s*\(?([1-5]\d{2})\b"
    r"|\bHTTP(?:/\d(?:\.\d)?)?[\s:=]+([1-5]\d{2})\b"
    r"|\bstatus(?: code)?[\s:=]+([1-5]\d{2})\b"
    r"|\b([1-5]\d{2}) (?:Client|Server) Error\b",
    re.IGNORECASE,
)

FailureKind = Literal["throttled", "rejected", "server", "client", "unreachable", "other"]

_UPSTREAM_ERRORS: dict[str, tuple[str, str]] = {
    "throttled": ("Rate limited by Garmin API.", "RATE_LIMITED"),
    "rejected": ("Authentication failed.", "AUTH_FAILED"),
    "server": ("Garmin API server error.", "SERVER_ERROR"),
    "unreachable": ("Could not reach Garmin.", "NETWORK_ERROR"),
}
# Kinds (and their error codes) that say nothing about the request or the credentials.
TRANSIENT_KINDS: frozenset[str] = frozenset({"throttled", "server", "unreachable"})
TRANSIENT_ERROR_CODES: frozenset[str] = frozenset(
    _UPSTREAM_ERRORS[kind][1] for kind in TRANSIENT_KINDS
)


class _UpstreamTypes(NamedTuple):
    transport: tuple[type[BaseException], ...]
    http: tuple[type[BaseException], ...]
    read_timeouts: tuple[type[BaseException], ...]  # the request may have been sent
    connect_timeouts: tuple[type[BaseException], ...]
    too_many_requests: type[BaseException]
    authentication: type[BaseException]


@functools.cache
def _upstream_types() -> _UpstreamTypes:
    """Upstream exception classes.

    Imported lazily: the CLI imports this module and keeps --help/--version
    free of the HTTP stack (tests/test_cli_lazy.py).
    """
    import socket
    import ssl

    import requests
    from garminconnect import (
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )

    transport: list[type[BaseException]] = [
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ChunkedEncodingError,
        ConnectionError,
        TimeoutError,
        socket.gaierror,
        ssl.SSLError,
    ]
    http: list[type[BaseException]] = [
        requests.RequestException,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    ]
    read_timeouts: list[type[BaseException]] = [requests.Timeout, TimeoutError]
    connect_timeouts: list[type[BaseException]] = [requests.ConnectTimeout]
    try:
        from curl_cffi.requests import exceptions as curl
    except ImportError:
        pass
    else:
        names = ("Timeout", "ConnectionError", "ChunkedEncodingError", "ProxyError", "IncompleteRead", "InterfaceError")
        transport += [getattr(curl, name) for name in names if hasattr(curl, name)]
        http.append(curl.RequestException)
        read_timeouts.append(curl.Timeout)
        connect_timeouts += [getattr(curl, name) for name in ("ConnectTimeout",) if hasattr(curl, name)]
    return _UpstreamTypes(
        tuple(transport),
        tuple(http),
        tuple(read_timeouts),
        tuple(connect_timeouts),
        GarminConnectTooManyRequestsError,
        GarminConnectAuthenticationError,
    )


def _exception_chain(exc: Any) -> list[Any]:
    """*exc* and its causes: ``__cause__``, else an unsuppressed ``__context__``.

    Stops at a GarminCliError: a failure raised while handling an earlier,
    already classified one (say a timeout during cleanup after a 429) must be
    judged on its own.
    """
    chain: list[Any] = [exc]
    current = exc
    while isinstance(current, BaseException):
        nxt = current.__cause__
        if nxt is None and not current.__suppress_context__:
            nxt = current.__context__
        if nxt is None or isinstance(nxt, GarminCliError) or any(nxt is link for link in chain):
            break
        chain.append(nxt)
        current = nxt
    return chain


def _response_status(exc: Any) -> int | None:
    for holder in (exc, getattr(exc, "error", None)):  # .error: legacy garth HTTP errors
        status = getattr(getattr(holder, "response", None), "status_code", None)
        if isinstance(status, int):
            return status
    return None


def _chain_status(chain: list[Any]) -> int | None:
    for link in chain:
        status = _response_status(link)
        if status is not None:
            return status
    for link in chain:
        match = _STATUS_RE.search(str(link))
        if match is not None:
            return int(next(group for group in match.groups() if group))
    return None


def extract_status_code(exc: Exception) -> int | None:
    """HTTP status of *exc*: a response anywhere in its chain, else explicit status wording."""
    return _chain_status(_exception_chain(exc))


def failure_kind(exc: Exception, *, login: bool = False) -> FailureKind:
    """Classify an upstream failure.

    throttled (429/427 or a TooManyRequests error), rejected (401/403, or an
    authentication error with no other evidence), server (5xx, 408, 425),
    client (other 4xx), unreachable (a transport error in the chain), or other
    (local failures such as a bad payload or token file).

    ``login=True`` is for SSO login steps only: a bot challenge counts as
    throttled, and "All login strategies exhausted" without a status is
    unreachable. On data and write calls the HTTP status alone decides.
    """
    types = _upstream_types()
    chain = _exception_chain(exc)
    status = _chain_status(chain)
    texts = [str(e).lower() for e in chain]
    if (
        status in (427, 429)
        or any(isinstance(e, types.too_many_requests) for e in chain)
        or (login and any("bot challenge" in text for text in texts))
    ):
        return "throttled"
    # Status and transport evidence first: upstream wraps 5xx and timeouts
    # during its profile load in GarminConnectAuthenticationError.
    if status is not None:
        if status in (401, 403):
            return "rejected"
        if status >= 500 or status in (408, 425):
            return "server"
        if status >= 400:
            return "client"
    if any(isinstance(e, types.transport) for e in chain):
        return "unreachable"
    # Upstream raises this unchained after every SSO strategy failed for
    # non-credential reasons (wrong credentials stop the chain immediately).
    if login and any("all login strategies exhausted" in text for text in texts):
        return "unreachable"
    if any(isinstance(e, types.authentication) for e in chain):
        return "rejected"
    return "other"


def may_have_been_processed(exc: Exception) -> bool:
    """True for a 5xx or a read timeout: Garmin may have applied the request.

    Connection failures (refused, DNS, connect timeouts) never reached it.
    """
    types = _upstream_types()
    chain = _exception_chain(exc)
    status = _chain_status(chain)
    if status is not None:
        return status >= 500 or status in (408, 425)
    return any(
        isinstance(e, types.read_timeouts) and not isinstance(e, types.connect_timeouts)
        for e in chain
    )


def upstream_error(kind: FailureKind, status: int | None = None) -> GarminCliError | None:
    """The GarminCliError for a classified failure; None for ``other`` (not upstream's doing)."""
    if kind == "client":
        return GarminCliError(
            error=f"Garmin rejected the request (HTTP {status}).", error_code="INVALID_INPUT"
        )
    if kind in _UPSTREAM_ERRORS:
        error, error_code = _UPSTREAM_ERRORS[kind]
        return GarminCliError(error=error, error_code=error_code)
    return None


def login_error(
    exc: Exception, rejected: str = "Authentication failed. Check your credentials."
) -> GarminCliError:
    """Map a failed login/MFA step; only *rejected* failures blame the credentials."""
    error, error_code = {
        "throttled": ("Garmin login is temporarily rate limited. Try again shortly.", "RATE_LIMITED"),
        "rejected": (rejected, "AUTH_FAILED"),
        "server": ("Garmin returned a server error during login. Try again later.", "SERVER_ERROR"),
        "unreachable": (
            "Could not reach Garmin to log in. Check connectivity and try again.",
            "NETWORK_ERROR",
        ),
    }.get(failure_kind(exc, login=True), ("Garmin login failed. Try again later.", "AUTH_FAILED"))
    return GarminCliError(error=error, error_code=error_code)


def probe_error(exc: Exception) -> GarminCliError | None:
    """Classify a failed session probe; None when Garmin rejected the session (log in again).

    Throttles, 5xx and network failures say nothing about the saved session,
    so they keep their own codes instead of AUTH_FAILED.
    """
    kind = failure_kind(exc)
    if kind == "rejected":
        return None
    if kind in TRANSIENT_KINDS:
        return upstream_error(kind)
    return GarminCliError(
        error="Saved Garmin session could not be validated.", error_code="AUTH_FAILED"
    )


def raise_unless_rejected(exc: Exception) -> None:
    """Raise the classified probe error; return only when Garmin rejected the session."""
    error = probe_error(exc)
    if error is not None:
        raise error from exc


def resume_error(exc: Exception) -> GarminCliError | None:
    """Classify a failed session resume; None when the saved session is missing or unusable.

    Resuming makes profile/settings requests, so a throttle, 5xx or network
    failure keeps its code (never a credential login). requests' and
    curl_cffi's errors are OSErrors too; only a filesystem OSError (other than
    a missing token file) is a session-directory error.
    """
    kind = failure_kind(exc)
    if kind in TRANSIENT_KINDS:
        return upstream_error(kind)
    http = _upstream_types().http
    if (
        isinstance(exc, OSError)
        and not isinstance(exc, FileNotFoundError)
        and not any(isinstance(e, http) for e in _exception_chain(exc))
    ):
        return GarminCliError(
            error=f"Cannot access session directory: {exc}", error_code="AUTH_FAILED"
        )
    return None
