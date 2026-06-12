"""Serializers for device-domain Garmin Connect payloads."""
from __future__ import annotations

from typing import Any

from garmin_cli.serializers._common import _listify

COLUMNS_DEVICE = ("device_id", "display_name", "device_type", "last_sync_time")


def serialize_device(raw: Any) -> list[dict[str, Any]]:
    return [
        {
            "device_id": item.get("deviceId"),
            "display_name": item.get("displayName"),
            "device_type": item.get("deviceTypeName"),
            "last_sync_time": item.get("lastSyncTime"),
        }
        for item in _listify(raw)
    ]
