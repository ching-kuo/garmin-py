"""Serializers for device-domain Garmin Connect payloads."""
from __future__ import annotations

from typing import Any

from garmin_cli.metrics import FieldEntry, FieldTable
from garmin_cli.serializers._common import _listify


_DEVICE_TABLE = FieldTable(
    entries=(
        FieldEntry("device_id", (("deviceId",),)),
        FieldEntry("display_name", (("displayName",),)),
        FieldEntry("device_type", (("deviceTypeName",),)),
        FieldEntry("last_sync_time", (("lastSyncTime",),)),
    ),
)
COLUMNS_DEVICE = _DEVICE_TABLE.columns


def serialize_device(raw: Any) -> list[dict[str, Any]]:
    return _DEVICE_TABLE.project_all(_listify(raw))
