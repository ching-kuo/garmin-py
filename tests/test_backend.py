"""Tests for the maintained Garmin backend compatibility boundary."""
from __future__ import annotations

import os
import stat
import threading
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

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
        self.run_request_kwargs: list[dict[str, Any]] = []

    def _run_request(self, method: str, path: str, **kwargs: Any) -> _FakeResponse:
        self.run_request_kwargs.append({"method": method, "path": path, **kwargs})
        return _FakeResponse(200, {})

    def _refresh_session(self) -> None:  # wrapped by backend._serialize_refresh
        pass

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
    assert capabilities == {"workout_update"}


class TestTypedWriteWrappers:
    """The new typed wrappers delegate to the upstream client verbatim."""

    def test_set_activity_name_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MagicMock()
        monkeypatch.setattr(backend, "_backend", client)

        backend.set_activity_name(12345, "Morning Run")

        client.set_activity_name.assert_called_once_with("12345", "Morning Run")

    def test_set_activity_type_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MagicMock()
        monkeypatch.setattr(backend, "_backend", client)

        backend.set_activity_type(12345, 2, "cycling", 17)

        client.set_activity_type.assert_called_once_with("12345", 2, "cycling", 17)

    def test_get_activity_types_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MagicMock()
        client.get_activity_types.return_value = [{"typeKey": "running"}]
        monkeypatch.setattr(backend, "_backend", client)

        assert backend.get_activity_types() == [{"typeKey": "running"}]

    def test_unschedule_workout_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MagicMock()
        monkeypatch.setattr(backend, "_backend", client)

        backend.unschedule_workout(555)

        client.unschedule_workout.assert_called_once_with(555)


class TestResolveHttpTimeout:
    @pytest.mark.parametrize(
        "env_value",
        (None, "not-a-number", "0", "-5", ""),
        ids=("unset", "non-numeric", "zero", "negative", "empty"),
    )
    def test_falls_back_to_default_when_env_unset_or_invalid(
        self, monkeypatch: pytest.MonkeyPatch, env_value: str | None
    ) -> None:
        if env_value is None:
            monkeypatch.delenv("GARMIN_CLI_HTTP_TIMEOUT", raising=False)
        else:
            monkeypatch.setenv("GARMIN_CLI_HTTP_TIMEOUT", env_value)
        assert backend._resolve_http_timeout() == 30.0

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_CLI_HTTP_TIMEOUT", "45.5")
        assert backend._resolve_http_timeout() == 45.5


class TestApplyTimeout:
    def test_login_calls_apply_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        monkeypatch.setattr(backend, "Garmin", _FakeGarmin)
        captured: list[Any] = []
        monkeypatch.setattr(backend, "_apply_timeout", lambda g: captured.append(g))

        backend.login("user@example.com", "secret", garth_home=str(garth_home))

        assert len(captured) == 1
        assert captured[0] is _FakeGarmin.instances[0]

    def test_resume_calls_apply_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        (garth_home / "garmin_tokens.json").write_text('{"di_token":"abc"}')
        monkeypatch.setattr(backend, "Garmin", _FakeGarmin)
        captured: list[Any] = []
        monkeypatch.setattr(backend, "_apply_timeout", lambda g: captured.append(g))

        backend.resume(str(garth_home))

        assert len(captured) == 1
        assert captured[0] is _FakeGarmin.instances[0]

    def test_apply_timeout_wraps_run_request_with_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GARMIN_CLI_HTTP_TIMEOUT", raising=False)
        fake_garmin = _FakeGarmin()
        backend._apply_timeout(fake_garmin)  # type: ignore[arg-type]

        fake_garmin.client._run_request("GET", "/test")

        assert fake_garmin.client.run_request_kwargs[-1]["timeout"] == 30.0

    def test_apply_timeout_uses_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GARMIN_CLI_HTTP_TIMEOUT", "60")
        fake_garmin = _FakeGarmin()
        backend._apply_timeout(fake_garmin)  # type: ignore[arg-type]

        fake_garmin.client._run_request("GET", "/test")

        assert fake_garmin.client.run_request_kwargs[-1]["timeout"] == 60.0

    def test_apply_timeout_does_not_override_explicit_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GARMIN_CLI_HTTP_TIMEOUT", raising=False)
        fake_garmin = _FakeGarmin()
        backend._apply_timeout(fake_garmin)  # type: ignore[arg-type]

        fake_garmin.client._run_request("GET", "/test", timeout=5)

        assert fake_garmin.client.run_request_kwargs[-1]["timeout"] == 5

    def test_apply_timeout_invalid_env_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GARMIN_CLI_HTTP_TIMEOUT", "bad")
        fake_garmin = _FakeGarmin()
        backend._apply_timeout(fake_garmin)  # type: ignore[arg-type]

        fake_garmin.client._run_request("GET", "/test")

        assert fake_garmin.client.run_request_kwargs[-1]["timeout"] == 30.0


# ---------------------------------------------------------------------------
# Lock / concurrency tests
# ---------------------------------------------------------------------------

class TestBackendLock:

    def test_set_backend_is_thread_safe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple threads calling _set_backend concurrently must not corrupt state."""
        monkeypatch.setattr(backend, "_backend", None)
        monkeypatch.setattr(backend, "_garth_home", None)

        n_threads = 20
        barrier = threading.Barrier(n_threads)
        errors: list[Exception] = []

        fake_clients = [SimpleNamespace(client=_FakeClient()) for _ in range(n_threads)]

        def _worker(idx: int) -> None:
            try:
                barrier.wait()
                backend._set_backend(
                    fake_clients[idx],  # type: ignore[arg-type]
                    garth_home=f"/tmp/home_{idx}",
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=_worker, args=(i,)) for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # After all writes, the singleton must be one of the fake clients.
        assert backend._backend in fake_clients

    def test_require_backend_raises_when_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(backend, "_backend", None)
        with pytest.raises(RuntimeError, match="not authenticated"):
            backend._require_backend()

    def test_require_backend_returns_client_when_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = SimpleNamespace(client=_FakeClient())
        monkeypatch.setattr(backend, "_backend", fake)
        result = backend._require_backend()
        assert result is fake

    def test_set_backend_updates_both_globals(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(backend, "_backend", None)
        monkeypatch.setattr(backend, "_garth_home", None)

        fake = SimpleNamespace(client=_FakeClient())
        backend._set_backend(fake, garth_home="/tmp/test_home")  # type: ignore[arg-type]

        assert backend._backend is fake
        assert backend._garth_home == "/tmp/test_home"

    def test_concurrent_require_backend_never_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_require_backend called from many threads must always return the set client."""
        fake = SimpleNamespace(client=_FakeClient())
        monkeypatch.setattr(backend, "_backend", fake)

        n_threads = 30
        barrier = threading.Barrier(n_threads)
        results: list[Any] = []
        errors: list[Exception] = []

        def _worker() -> None:
            try:
                barrier.wait()
                results.append(backend._require_backend())
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert all(r is fake for r in results)


class TestSerializeRefresh:
    """_serialize_refresh: only one token refresh runs under concurrent fan-out."""

    class _RefreshInner:
        def __init__(self) -> None:
            self._generation = 0
            self.generation_reads: list[str] = []
            self.refresh_calls = 0
            self.entered = threading.Event()
            self.release = threading.Event()

        @property
        def _garmin_cli_refresh_generation(self) -> int:
            self.generation_reads.append(threading.current_thread().name)
            return self._generation

        @_garmin_cli_refresh_generation.setter
        def _garmin_cli_refresh_generation(self, value: int) -> None:
            self._generation = value

        def _refresh_session(self) -> None:
            self.refresh_calls += 1
            self.entered.set()
            assert self.release.wait(timeout=10)

    def test_waiting_thread_skips_refresh_after_one_completes(self) -> None:
        inner = self._RefreshInner()
        backend._serialize_refresh(SimpleNamespace(client=inner))

        first = threading.Thread(target=inner._refresh_session, name="first")
        first.start()
        assert inner.entered.wait(timeout=10)  # first holds the lock, mid-refresh

        second = threading.Thread(target=inner._refresh_session, name="second")
        second.start()
        # Wait until the second thread captured its generation snapshot, so it
        # is deterministically queued behind the in-flight refresh.
        for _ in range(1000):
            if "second" in inner.generation_reads:
                break
            first.join(timeout=0.01)
        assert "second" in inner.generation_reads

        inner.release.set()
        first.join(timeout=10)
        second.join(timeout=10)
        assert not first.is_alive() and not second.is_alive()

        assert inner.refresh_calls == 1
        assert inner._generation == 1

    def test_sequential_refreshes_both_run(self) -> None:
        inner = self._RefreshInner()
        inner.release.set()
        backend._serialize_refresh(SimpleNamespace(client=inner))

        inner._refresh_session()
        assert inner.refresh_calls == 1
        inner._refresh_session()
        assert inner.refresh_calls == 2
        assert inner._generation == 2
