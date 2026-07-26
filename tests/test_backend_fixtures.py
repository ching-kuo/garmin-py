"""Tests for sanitized backend-boundary recording and replay."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from garmin_cli import backend
from tests.backend_fixtures import (
    BackendFixtureController,
    BackendFixtureStore,
    FixtureMissingError,
    fixture_key,
    sanitize,
)


def test_sanitize_scrubs_every_identity_and_secret_key_recursively() -> None:
    payload = {
        "displayName": "athlete",
        "FULLNAME": "Athlete Example",
        "firstName": "Athlete",
        "lastName": "Example",
        "emailAddress": "athlete@example.test",
        "userProfileId": 123,
        "userProfilePk": 456,
        "profileImageUrlLarge": "https://example.test/private.jpg",
        "location": "Private place",
        "startLatitude": 35.1,
        "startLongitude": 139.1,
        "endLatitude": 35.2,
        "endLongitude": 139.2,
        "nested": [
            {
                "accessToken": "token-value",
                "PASSWORD_HINT": "secret-value",
                "clientSecret": "secret-value",
            }
        ],
        "safe": "kept",
    }

    result = sanitize(payload)

    assert result == {
        "displayName": "REDACTED",
        "FULLNAME": "REDACTED",
        "firstName": "REDACTED",
        "lastName": "REDACTED",
        "emailAddress": "REDACTED",
        "userProfileId": 0,
        "userProfilePk": 0,
        "profileImageUrlLarge": "REDACTED",
        "location": "REDACTED",
        "startLatitude": 0.0,
        "startLongitude": 0.0,
        "endLatitude": 0.0,
        "endLongitude": 0.0,
        "nested": [{
            "accessToken": "REDACTED",
            "PASSWORD_HINT": "REDACTED",
            "clientSecret": "REDACTED",
        }],
        "safe": "kept",
    }


def test_recording_same_call_twice_is_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = 0

    def fake_connectapi(
        path: str,
        method: str = "GET",
        *,
        capability: str | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "date": "2026-07-01",
            "displayName": "private-athlete",
            "values": [3, 1, 2],
        }

    monkeypatch.setattr(backend, "connectapi", fake_connectapi)
    BackendFixtureController("record", tmp_path).install(monkeypatch)
    arguments = {
        "path": "/wellness-service/wellness/dailySleeps",
        "params": {"startDate": "2026-07-01", "endDate": "2026-07-01"},
    }

    backend.connectapi(arguments["path"], params=arguments["params"])
    path = BackendFixtureStore(tmp_path).path_for("connectapi", arguments)
    first = path.read_bytes()
    backend.connectapi(arguments["path"], params=arguments["params"])

    assert calls == 2
    assert path.read_bytes() == first
    assert b"private-athlete" not in first


def test_replay_returns_payload_and_missing_fixture_names_record_command(
    tmp_path: Path,
) -> None:
    store = BackendFixtureStore(tmp_path)
    arguments = {"cdate": "2026-07-01"}
    store.record("get_heart_rates", arguments, {"calendarDate": "2026-07-01"})

    assert store.replay("get_heart_rates", arguments) == {
        "calendarDate": "2026-07-01"
    }
    with pytest.raises(FixtureMissingError, match=r"--e2e --record-fixtures"):
        store.replay("get_heart_rates", {"cdate": "2026-07-02"})


def test_fixture_keys_hash_numeric_identifiers_and_cap_length() -> None:
    key = fixture_key(
        "connectapi",
        {
            "path": "/activity-service/activity/987654321/splits",
            "params": {"activity_id": 123456789, "search": "x" * 300},
        },
    )

    assert "987654321" not in key
    assert "123456789" not in key
    assert len(key) <= 180


def test_committed_fixtures_exclude_configured_identity_markers() -> None:
    raw_markers = os.environ.get("GARMIN_FIXTURE_IDENTITY_MARKERS", "")
    markers = [marker.strip() for marker in raw_markers.split(",") if marker.strip()]
    if not markers:
        pytest.skip("GARMIN_FIXTURE_IDENTITY_MARKERS is not set")
    fixture_root = Path(__file__).parent / "fixtures"
    corpus = "\n".join(
        path.read_text(errors="replace")
        for path in fixture_root.rglob("*.json")
    ).lower()
    for marker in markers:
        assert marker.lower() not in corpus


def test_committed_fixture_corpus_is_already_sanitized() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "backend"
    fixture_paths = sorted(fixture_root.rglob("*.json"))

    assert 15 <= len(fixture_paths) <= 25
    for path in fixture_paths:
        payload = json.loads(path.read_text())
        assert sanitize(payload) == payload, f"unsanitized identity field in {path.name}"
