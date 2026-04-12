"""Tests for the maintained Garmin backend compatibility boundary."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from garmin_cli import backend


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    def __init__(self) -> None:
        self.dump_calls: list[str] = []
        self.put_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def dump(self, path: str) -> None:
        self.dump_calls.append(path)
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "garmin_tokens.json").write_text('{"di_token":"abc"}')

    def put(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        self.put_calls.append((args, kwargs))
        return _FakeResponse(204, {})


class _FakeGarmin:
    instances: list["_FakeGarmin"] = []

    def __init__(self, email: str | None = None, password: str | None = None, prompt_mfa: Any = None) -> None:
        self.email = email
        self.password = password
        self.prompt_mfa = prompt_mfa
        self.client = _FakeClient()
        self.login_calls: list[str | None] = []
        self.garmintokens_env_at_login: str | None = None
        _FakeGarmin.instances.append(self)

    def login(self, /, tokenstore: str | None = None) -> tuple[None, None]:
        self.login_calls.append(tokenstore)
        self.garmintokens_env_at_login = os.environ.get("GARMINTOKENS")
        return None, None


@pytest.fixture(autouse=True)
def _reset_backend_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend, "_backend", None)
    monkeypatch.setattr(backend, "_garth_home", None)
    _FakeGarmin.instances.clear()


class TestResume:
    def test_resume_uses_explicit_garth_home_instead_of_garmintokens(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        (garth_home / "garmin_tokens.json").write_text('{"di_token":"abc"}')
        monkeypatch.setenv("GARMINTOKENS", str(tmp_path / "ignored.json"))
        monkeypatch.setattr(backend, "Garmin", _FakeGarmin)

        backend.resume(str(garth_home))

        assert _FakeGarmin.instances[0].login_calls == [str(garth_home)]


class TestLogin:
    def test_login_uses_explicit_garth_home_for_fresh_auth(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        monkeypatch.setenv("GARMINTOKENS", str(tmp_path / "ignored.json"))
        monkeypatch.setattr(backend, "Garmin", _FakeGarmin)

        backend.login("user@example.com", "secret", garth_home=str(garth_home))

        instance = _FakeGarmin.instances[0]
        assert instance.login_calls == [None]
        assert instance.garmintokens_env_at_login is None
        assert backend._garth_home == str(garth_home)

    def test_resume_rejects_legacy_tokens_without_new_tokenstore(self, tmp_path: Path) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        (garth_home / "oauth1_token.json").write_text("{}")
        (garth_home / "oauth2_token.json").write_text("{}")

        with pytest.raises(FileNotFoundError, match="Legacy garth session files"):
            backend.resume(str(garth_home))


class TestSave:
    def test_save_creates_secure_directory_and_token_file(self, tmp_path: Path) -> None:
        garth_home = tmp_path / "garth"
        fake = SimpleNamespace(client=_FakeClient())
        backend._backend = fake  # type: ignore[assignment]

        backend.save(str(garth_home))

        token_file = garth_home / "garmin_tokens.json"
        assert token_file.exists()
        assert stat.S_IMODE(garth_home.stat().st_mode) == 0o700
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


class TestConnectApi:
    def test_put_returns_none_for_204(self) -> None:
        fake = SimpleNamespace(client=_FakeClient())
        backend._backend = fake  # type: ignore[assignment]

        result = backend.connectapi(
            "/workout-service/workout/12345",
            method="PUT",
            json={"workoutId": 12345},
        )

        assert result is None


def test_raw_fallback_registry_tracks_update_paths() -> None:
    capabilities = {entry["capability"] for entry in backend.get_raw_fallback_registry()}
    assert capabilities == {"workout_update", "workout_description_update"}
