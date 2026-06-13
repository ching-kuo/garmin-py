"""Maintained Garmin backend compatibility boundary."""
from __future__ import annotations

import logging
import os
import threading
import types
from datetime import date
from typing import Any

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


RAW_FALLBACKS: tuple[dict[str, str], ...] = (
    {
        "capability": "workout_update",
        "why": "Upstream provides no typed workout update helper.",
        "transport": "Garmin.client.put('connectapi', '/workout-service/workout/{id}', json=payload)",
        "tests": "tests/test_endpoints/test_workouts_write.py, tests/test_backend.py",
        "removal_condition": "Use an upstream typed update method once python-garminconnect exposes one.",
    },
    {
        "capability": "workout_description_update",
        "why": "garmin.api.update_workout_description mutates an existing workout via PUT after merging description text.",
        "transport": "Garmin.client.put('connectapi', '/workout-service/workout/{id}', json=payload)",
        "tests": "tests/test_backend.py",
        "removal_condition": "Use an upstream typed update method once python-garminconnect exposes one.",
    },
)

_backend: Garmin | None = None
_garth_home: str | None = None


def get_raw_fallback_registry() -> list[dict[str, str]]:
    """Return the governed raw-fallback table for this backend."""
    return [dict(entry) for entry in RAW_FALLBACKS]


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


def _normalize_home(path: str | None = None) -> str | None:
    if path is None:
        with _backend_lock:
            return _garth_home
    return str(ensure_secure_directory(path))


def login(
    email: str,
    password: str,
    *,
    garth_home: str | None = None,
    prompt_mfa: Any = None,
) -> None:
    """Authenticate with Garmin Connect without persisting the tokenstore yet."""
    normalized_home = _normalize_home(garth_home)
    client = Garmin(email, password, prompt_mfa=prompt_mfa)
    _apply_timeout(client)
    previous_env = os.environ.pop("GARMINTOKENS", None)
    try:
        client.login()
    finally:
        if previous_env is not None:
            os.environ["GARMINTOKENS"] = previous_env
    if normalized_home is not None:
        client.client._tokenstore_path = normalized_home
    _set_backend(client, normalized_home)
    logger.debug("Garmin login succeeded for configured account")


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


def connectapi(
    path: str,
    method: str = "GET",
    *,
    capability: str | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | list[Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Compatibility wrapper matching the old `garth.connectapi` surface."""
    client = _require_backend()
    method = method.upper()

    if method == "GET":
        return client.connectapi(path, params=params, **kwargs)

    capability_name = capability or f"{method.lower()}:{path}"
    logger.debug(
        "Raw fallback used for capability=%s method=%s path=%s",
        capability_name,
        method,
        path,
    )
    if method == "POST":
        request_fn = client.client.post
    elif method == "PUT":
        request_fn = client.client.put
    elif method == "DELETE":
        request_fn = client.client.delete
    else:
        raise ValueError(f"Unsupported Garmin API method: {method}")

    response = request_fn("connectapi", path, params=params, json=json, **kwargs)
    if response is None:
        return None
    if hasattr(response, "status_code") and response.status_code == 204:
        return None
    if hasattr(response, "json"):
        return response.json()
    return response


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


def delete_workout(workout_id: int | str) -> Any:
    """Use the typed upstream workout delete helper."""
    client = _require_backend()
    return client.delete_workout(workout_id)


def schedule_workout(workout_id: int | str, schedule_date: date | str) -> dict[str, Any]:
    """Use the typed upstream workout schedule helper."""
    client = _require_backend()
    date_str = schedule_date if isinstance(schedule_date, str) else schedule_date.isoformat()
    return client.schedule_workout(workout_id, date_str)


def get_activity_typed_splits(activity_id: int | str) -> Any:
    """Use the typed upstream typed-splits helper (per-pool-length swim data)."""
    client = _require_backend()
    return client.get_activity_typed_splits(activity_id)


def get_activity_details(activity_id: int | str) -> Any:
    """Use the typed upstream activity-details helper (metric stream + descriptors)."""
    client = _require_backend()
    return client.get_activity_details(activity_id)


def get_activity_hr_in_timezones(activity_id: int | str) -> Any:
    """Use the typed upstream HR-time-in-zone helper."""
    client = _require_backend()
    return client.get_activity_hr_in_timezones(activity_id)


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
