"""Sanitized backend-boundary fixture recording and replay."""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from garmin_cli import backend

RECORDABLE_BACKEND_FUNCTIONS: tuple[str, ...] = (
    "connectapi",
    "get_activity_details",
    "get_activity_hr_in_timezones",
    "get_activity_typed_splits",
    "get_activity_types",
    "get_heart_rates",
    "get_personal_records",
    "get_race_predictions",
    "get_workout",
    "list_workouts",
)

_IDENTITY_KEYS = frozenset({
    "displayname",
    "fullname",
    "firstname",
    "lastname",
    "emailaddress",
    "userprofileid",
    "userprofilepk",
    "location",
    "startlatitude",
    "startlongitude",
    "endlatitude",
    "endlongitude",
})
_SECRET_FRAGMENTS = ("token", "password", "secret")
_SLUG_RE = re.compile(r"[^a-zA-Z0-9._=-]+")
_NUMERIC_PATH_SEGMENT = re.compile(r"(?<=/)\d+(?=/|$)")


class FixtureMissingError(FileNotFoundError):
    """Raised when replay cannot find the deterministic backend fixture."""


def _sensitive_key(key: Any) -> bool:
    lowered = str(key).lower()
    return (
        lowered in _IDENTITY_KEYS
        or lowered.startswith("profileimageurl")
        or any(fragment in lowered for fragment in _SECRET_FRAGMENTS)
    )


def _placeholder(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        return 0.0
    if isinstance(value, int):
        return 0
    if isinstance(value, str):
        return "REDACTED"
    if isinstance(value, (list, tuple)):
        return []
    if isinstance(value, dict):
        return {}
    return None


def sanitize(payload: Any) -> Any:
    """Recursively redact identity and secret fields while preserving types."""
    if isinstance(payload, Mapping):
        return {
            key: _placeholder(value) if _sensitive_key(key) else sanitize(value)
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [sanitize(value) for value in payload]
    return payload


def _short_hash(value: Any, length: int = 10) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:length]


def _safe_value(name: str, value: Any) -> str:
    if _sensitive_key(name):
        return "redacted"
    if name.lower().endswith(("id", "_id", "pk", "_pk")):
        return "id-" + _short_hash(value, 8)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return ",".join(
            f"{key}={_safe_value(str(key), item)}"
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple)):
        return ",".join(_safe_value(name, item) for item in value)
    text = str(value)
    if name == "path":
        text = _NUMERIC_PATH_SEGMENT.sub(
            lambda match: "id-" + _short_hash(match.group(0), 8),
            text,
        )
    return _SLUG_RE.sub("-", text.strip("/")).strip("-") or "empty"


def fixture_key(function_name: str, arguments: Mapping[str, Any]) -> str:
    """Build a deterministic, identifier-safe fixture key."""
    parts = [function_name]
    for name, value in arguments.items():
        if value is None:
            continue
        if function_name == "connectapi" and name == "path":
            parts.append(_safe_value(name, value))
        elif isinstance(value, Mapping):
            flattened = _safe_value(name, value)
            if flattened:
                parts.append(flattened)
        else:
            parts.append(f"{name}={_safe_value(name, value)}")
    key = "__".join(parts)
    if len(key) > 180:
        key = f"{key[:160].rstrip('-_')}__{_short_hash(arguments, 16)}"
    return key


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Backend fixture payload is not JSON serializable: {type(value).__name__}")


class BackendFixtureStore:
    """Read and write stable JSON fixtures below one root directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, function_name: str, arguments: Mapping[str, Any]) -> Path:
        return self.root / function_name / f"{fixture_key(function_name, arguments)}.json"

    def record(
        self,
        function_name: str,
        arguments: Mapping[str, Any],
        payload: Any,
    ) -> Path:
        path = self.path_for(function_name, arguments)
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(
            sanitize(payload),
            indent=2,
            sort_keys=True,
            default=_json_default,
        ) + "\n"
        path.write_text(rendered)
        return path

    def replay(self, function_name: str, arguments: Mapping[str, Any]) -> Any:
        path = self.path_for(function_name, arguments)
        if not path.exists():
            raise FixtureMissingError(
                f"Missing backend fixture: {path}. Record it with "
                "pytest --e2e --record-fixtures."
            )
        return json.loads(path.read_text())


class BackendFixtureController:
    """Patch the recordable backend read functions in record or replay mode."""

    def __init__(self, mode: str, root: Path) -> None:
        if mode not in {"record", "replay"}:
            raise ValueError("mode must be 'record' or 'replay'")
        self.mode = mode
        self.store = BackendFixtureStore(root)

    def install(self, monkeypatch: Any) -> None:
        for name in RECORDABLE_BACKEND_FUNCTIONS:
            real = getattr(backend, name)
            monkeypatch.setattr(backend, name, self._wrapper(name, real))

    def _wrapper(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(real)

        @wraps(real)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind_partial(*args, **kwargs)
            arguments = bound.arguments
            if self.mode == "replay":
                return self.store.replay(name, arguments)
            payload = real(*args, **kwargs)
            self.store.record(name, arguments, payload)
            return payload

        return wrapped
