"""Device endpoint helpers backed by Garmin Connect APIs."""
from __future__ import annotations

from typing import Any

import garth

from garmin_cli.endpoints._base import _make_request


def _request(url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _make_request(garth.connectapi, url, params=params)


def get_devices() -> list[Any]:
    result = _request("/device-service/deviceregistration/devices")
    if isinstance(result, dict):
        return [result]
    return result if result is not None else []


