"""Maintained Garmin backend compatibility boundary."""
from __future__ import annotations

import logging
import os
import threading
import types
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from garminconnect import Garmin

from garmin_cli._env import _env_float
from garmin_cli.token_store import (
    detect_legacy_tokens,
    ensure_secure_directory,
    has_tokenstore,
    secure_token_file,
)

logger = logging.getLogger(__name__)

_DEFAULT_HTTP_TIMEOUT: float = 30.0

# RLock so that the same thread can re-acquire (e.g. login -> _set_backend).
_backend_lock: threading.RLock = threading.RLock()


def _resolve_http_timeout() -> float:
    """Return the configured HTTP timeout in seconds.

    Reads ``GARMIN_CLI_HTTP_TIMEOUT`` from the environment.  Invalid or
    non-positive values are silently ignored and the default (30 s) is used.
    """
    return _env_float("GARMIN_CLI_HTTP_TIMEOUT", _DEFAULT_HTTP_TIMEOUT, allow_zero=False)


def _apply_timeout(garmin: Garmin) -> None:
    """Wrap *garmin.client._run_request* to enforce the configured timeout.

    The upstream ``garminconnect.client.Client._run_request`` injects
    ``timeout=15`` when the caller omits it.  We replace that default with
    our configurable value by wrapping the bound method at the instance level
    so every API call inherits it without touching the installed package.
    """
    timeout = _resolve_http_timeout()
    inner_client = garmin.client
    original_run_request = inner_client._run_request.__func__  # type: ignore[attr-defined]

    def _patched_run_request(self: Any, method: str, path: str, **kwargs: Any) -> Any:
        if "timeout" not in kwargs:
            kwargs["timeout"] = timeout
        return original_run_request(self, method, path, **kwargs)

    inner_client._run_request = types.MethodType(_patched_run_request, inner_client)  # type: ignore[method-assign]


# Process-wide: under parallel fan-out several worker threads can hit a 401
# simultaneously. Since 0.3.10 upstream serializes refreshes under its
# per-client _token_lock (an RLock taken before this one, so no lock-order
# inversion), but it still runs one refresh per 401'd thread back to back,
# which can burn a rotated (single-use) refresh token. The request-start
# generation guard below collapses those into one refresh.
_refresh_lock: threading.Lock = threading.Lock()


def _serialize_refresh(garmin: Garmin) -> None:
    """Wrap *garmin.client._refresh_session* so only one refresh runs at a time.

    A thread skips its refresh when a refresh completed after it built the
    auth headers of its rejected request: the 401 answered a token that has
    already been replaced, and upstream re-sends with fresh headers. A
    generation counter (not token identity) detects this, so the guard also
    covers legacy jwt_web sessions, whose refresh never touches ``di_token``.

    The snapshot is taken in ``get_api_headers`` (the token actually sent),
    not when the refresh starts: upstream (0.3.10+) already serializes
    refreshes under its ``_token_lock``, so a queued thread would otherwise
    always see an advanced generation. It is scoped to ``_run_request`` so a
    refresh called outside a request (upstream login paths) is never skipped.
    """
    inner_client = garmin.client
    original_refresh = inner_client._refresh_session.__func__  # type: ignore[attr-defined]
    original_run_request = inner_client._run_request
    original_headers = inner_client.get_api_headers
    sent = threading.local()
    inner_client._garmin_cli_refresh_generation = 0  # type: ignore[attr-defined]

    def _tracked_run_request(self: Any, method: str, path: str, **kwargs: Any) -> Any:
        try:
            return original_run_request(method, path, **kwargs)
        finally:
            sent.__dict__.pop("generation", None)

    def _tracked_headers(self: Any) -> Any:
        sent.generation = self._garmin_cli_refresh_generation
        return original_headers()

    def _locked_refresh(self: Any) -> None:
        with _refresh_lock:
            current = self._garmin_cli_refresh_generation
            if getattr(sent, "generation", current) != current:
                return
            original_refresh(self)
            self._garmin_cli_refresh_generation = current + 1

    inner_client._run_request = types.MethodType(_tracked_run_request, inner_client)  # type: ignore[method-assign]
    inner_client.get_api_headers = types.MethodType(_tracked_headers, inner_client)  # type: ignore[method-assign]
    inner_client._refresh_session = types.MethodType(_locked_refresh, inner_client)  # type: ignore[method-assign]


_backend: Garmin | None = None
_garth_home: str | None = None


def _require_backend() -> Garmin:
    with _backend_lock:
        if _backend is None:
            raise RuntimeError("Garmin backend is not authenticated")
        return _backend


def _set_backend(client: Garmin, garth_home: str | None = None) -> None:
    global _backend, _garth_home
    with _backend_lock:
        _backend = client
        _garth_home = garth_home


def profile_today() -> date | None:
    """Today in the Garmin profile timezone, or None when it is unknown.

    Best effort: None without an active session, when the profile has no
    valid timezone, or when the lookup fails. Upstream caches the lookup per
    client, and clients are rebuilt on auth-probe cache misses, so a failed
    lookup or a changed profile timezone is picked up by the next client.
    """
    with _backend_lock:
        client = _backend
    if client is None:
        return None
    try:
        timezone = client.get_user_timezone()
        if not isinstance(timezone, str) or not timezone:
            return None
        return datetime.now(ZoneInfo(timezone)).date()
    except Exception as exc:  # never block a read on the timezone lookup
        logger.debug("Garmin profile timezone unavailable: %s", type(exc).__name__)
        return None


def _normalize_home(path: str | None = None) -> str | None:
    if path is None:
        with _backend_lock:
            return _garth_home
    return str(ensure_secure_directory(path))


@dataclass(frozen=True)
class PendingMFA:
    """A login halted by Garmin awaiting an MFA code.

    Holds the half-authenticated client and the opaque SSO state needed by
    :func:`resume_mfa_login`. Never persisted; lives only in process memory.
    """

    client: Garmin
    client_state: dict[str, Any]
    garth_home: str | None


def login(
    email: str,
    password: str,
    *,
    garth_home: str | None = None,
    prompt_mfa: Any = None,
    return_on_mfa: bool = False,
) -> PendingMFA | None:
    """Authenticate with Garmin Connect without persisting the tokenstore yet.

    With ``return_on_mfa=True`` an MFA challenge does not block on
    ``prompt_mfa``; instead the half-finished login is returned as a
    :class:`PendingMFA` for the caller to complete via
    :func:`resume_mfa_login`. Returns ``None`` when login finished cleanly.
    """
    normalized_home = _normalize_home(garth_home)
    client = Garmin(email, password, prompt_mfa=prompt_mfa, return_on_mfa=return_on_mfa)
    _apply_timeout(client)
    _serialize_refresh(client)
    previous_env = os.environ.pop("GARMINTOKENS", None)
    try:
        result = client.login()
    finally:
        if previous_env is not None:
            os.environ["GARMINTOKENS"] = previous_env
    if return_on_mfa:
        if result is not None and result[0] == "needs_mfa":
            logger.debug("Garmin login halted awaiting an MFA code")
            return PendingMFA(client=client, client_state=result[1], garth_home=normalized_home)
        # Upstream's return_on_mfa mode early-returns even on a clean login,
        # skipping the profile/settings load that displayName-scoped endpoints
        # need. Replay login from the in-memory tokens to load them.
        client.login(tokenstore=client.client.dumps())
    _activate(client, normalized_home)
    logger.debug("Garmin login succeeded for configured account")
    return None


def _activate(client: Garmin, garth_home: str | None) -> None:
    """Make *client* the process-wide backend, pinned to *garth_home*."""
    if garth_home is not None:
        client.client._tokenstore_path = garth_home
    _set_backend(client, garth_home)


def resume_mfa_login(pending: PendingMFA, mfa_code: str) -> None:
    """Complete a login previously halted for MFA and activate the backend."""
    pending.client.resume_login(pending.client_state, mfa_code)
    _activate(pending.client, pending.garth_home)
    logger.debug("Garmin MFA login completed")


def resume(garth_home: str) -> None:
    """Restore an authenticated client from the configured Garmin home."""
    ensure_secure_directory(garth_home)

    if detect_legacy_tokens(garth_home) and not has_tokenstore(garth_home):
        logger.debug(
            "Legacy garth token files detected in %s; requiring a fresh login",
            garth_home,
        )
        raise FileNotFoundError("Legacy garth session files are not resumable")

    if not has_tokenstore(garth_home):
        raise FileNotFoundError("No garmin_tokens.json found in the Garmin home directory")

    client = Garmin()
    _apply_timeout(client)
    _serialize_refresh(client)
    client.login(tokenstore=garth_home)
    _set_backend(client, garth_home)
    logger.debug("Garmin session resumed from %s", garth_home)


def save(garth_home: str) -> None:
    """Persist the current backend tokenstore into the configured Garmin home."""
    with _backend_lock:
        client = _require_backend()
        directory = ensure_secure_directory(garth_home, create=True)
        client.client.dump(str(directory))
        secure_token_file(str(directory))
        _set_backend(client, str(directory))
    logger.debug("Garmin session saved to %s", garth_home)


def connectapi(path: str, *, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    """GET *path* on the Garmin Connect API (the old ``garth.connectapi`` surface).

    Writes go through the typed upstream helpers below.
    """
    client = _require_backend()
    return client.connectapi(path, params=params, **kwargs)


def list_workouts(limit: int) -> list[dict[str, Any]]:
    """Use the typed upstream workout listing helper."""
    client = _require_backend()
    return client.get_workouts(start=0, limit=limit)


def get_workout(workout_id: int | str) -> dict[str, Any]:
    """Use the typed upstream single-workout helper."""
    client = _require_backend()
    return client.get_workout_by_id(workout_id)


def create_workout(payload: dict[str, Any]) -> dict[str, Any]:
    """Use the typed upstream workout upload helper."""
    client = _require_backend()
    return client.upload_workout(payload)


def update_workout(workout_id: int | str, payload: dict[str, Any]) -> dict[str, Any]:
    """Use the typed upstream workout update helper (PUT, keeps the workout id)."""
    client = _require_backend()
    return client.update_workout(workout_id, payload)


def delete_workout(workout_id: int | str) -> Any:
    """Use the typed upstream workout delete helper."""
    client = _require_backend()
    return client.delete_workout(workout_id)


def schedule_workout(workout_id: int | str, schedule_date: date | str) -> dict[str, Any]:
    """Use the typed upstream workout schedule helper."""
    client = _require_backend()
    date_str = schedule_date if isinstance(schedule_date, str) else schedule_date.isoformat()
    return client.schedule_workout(workout_id, date_str)


def get_activity_types() -> list[dict[str, Any]]:
    """Use the typed upstream activity-types helper (sport typeKey/typeId table)."""
    client = _require_backend()
    # Upstream annotates dict; the endpoint actually returns a list.
    return cast(list[dict[str, Any]], client.get_activity_types())


def set_activity_name(activity_id: int | str, name: str) -> Any:
    """Use the typed upstream activity-rename helper (PUT title)."""
    client = _require_backend()
    return client.set_activity_name(str(activity_id), name)


def set_activity_type(
    activity_id: int | str,
    type_id: int,
    type_key: str,
    parent_type_id: int,
) -> Any:
    """Use the typed upstream activity-type helper (PUT activityTypeDTO)."""
    client = _require_backend()
    return client.set_activity_type(str(activity_id), type_id, type_key, parent_type_id)


def unschedule_workout(scheduled_workout_id: int | str) -> Any:
    """Use the typed upstream unschedule helper (removes a calendar entry)."""
    client = _require_backend()
    return client.unschedule_workout(scheduled_workout_id)


def get_activity_typed_splits(activity_id: int | str) -> Any:
    """Use the typed upstream typed-splits helper (per-pool-length swim data)."""
    client = _require_backend()
    return client.get_activity_typed_splits(str(activity_id))


def get_activity_details(activity_id: int | str) -> Any:
    """Use the typed upstream activity-details helper (metric stream + descriptors)."""
    client = _require_backend()
    return client.get_activity_details(str(activity_id))


def get_activity_hr_in_timezones(activity_id: int | str) -> Any:
    """Use the typed upstream HR-time-in-zone helper."""
    client = _require_backend()
    return client.get_activity_hr_in_timezones(str(activity_id))


def download_activity(activity_id: int | str, dl_fmt: Any) -> bytes:
    """Use the typed upstream activity-download helper.

    *dl_fmt* must be a ``Garmin.ActivityDownloadFormat`` enum member.
    Returns raw bytes — caller is responsible for writing to disk.
    """
    client = _require_backend()
    return client.download_activity(str(activity_id), dl_fmt=dl_fmt)


def upload_activity(activity_path: str) -> Any:
    """Use the typed upstream activity-upload helper.

    *activity_path* must exist on disk and have a FIT, GPX, or TCX extension.
    Returns the upstream response payload (shape varies by file format).
    """
    client = _require_backend()
    return client.upload_activity(activity_path)


def delete_activity(activity_id: int | str) -> Any:
    """Use the typed upstream activity-delete helper."""
    client = _require_backend()
    return client.delete_activity(str(activity_id))


def get_heart_rates(cdate: str) -> dict[str, Any]:
    """Use the typed upstream daily-heart-rate helper (displayName-scoped).

    The bare ``/wellness-service/wellness/dailyHeartRate/{day}`` path now
    403s; upstream scopes the same endpoint under the account displayName.
    """
    client = _require_backend()
    return client.get_heart_rates(cdate)


def get_race_predictions() -> dict[str, Any]:
    """Use the typed upstream race-predictions helper (displayName-scoped, latest).

    The bare ``/metrics-service/metrics/racepredictions`` path now 404s;
    upstream scopes the same endpoint under the account displayName.
    """
    client = _require_backend()
    return client.get_race_predictions()


def get_personal_records() -> Any:
    """Use the typed upstream personal-records helper (displayName-scoped)."""
    client = _require_backend()
    return client.get_personal_record()
