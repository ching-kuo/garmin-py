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
import requests

from garmin_cli import backend
from garmin_cli.exceptions import GarminCliError


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

    def _di_token_post(self, *args: Any) -> _FakeResponse:  # wrapped by backend._surface_refresh_failures
        return _FakeResponse(200, {})

    def get_api_headers(self) -> dict[str, str]:  # wrapped by backend._serialize_refresh
        return {}

    def dump(self, path: str) -> None:
        self.dump_calls.append(path)
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "garmin_tokens.json").write_text('{"di_token":"abc"}')

    def put(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        self.put_calls.append((args, kwargs))
        return _FakeResponse(204, {})

    def dumps(self) -> str:
        return '{"di_token":"abc"}' + " " * 600  # >512 chars: treated as token data, not a path


class _FakeGarmin:
    instances: list["_FakeGarmin"] = []
    mfa_required: bool = False  # class-level toggle set by MFA tests

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        prompt_mfa: Any = None,
        return_on_mfa: bool = False,
        retry_attempts: int = 3,
    ) -> None:
        self.retry_attempts = retry_attempts
        self.email = email
        self.password = password
        self.prompt_mfa = prompt_mfa
        self.return_on_mfa = return_on_mfa
        self.client = _FakeClient()
        self.login_calls: list[str | None] = []
        self.resume_login_calls: list[tuple[Any, str]] = []
        self.garmintokens_env_at_login: str | None = None
        _FakeGarmin.instances.append(self)

    def login(self, /, tokenstore: str | None = None) -> tuple[str | None, Any]:
        self.login_calls.append(tokenstore)
        self.garmintokens_env_at_login = os.environ.get("GARMINTOKENS")
        if self.return_on_mfa and _FakeGarmin.mfa_required:
            return "needs_mfa", {"signin_params": "opaque"}
        return None, None

    def resume_login(self, client_state: Any, mfa_code: str) -> tuple[None, None]:
        self.resume_login_calls.append((client_state, mfa_code))
        return None, None


@pytest.fixture(autouse=True)
def _reset_backend_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend, "_backend", None)
    monkeypatch.setattr(backend, "_garth_home", None)
    _FakeGarmin.instances.clear()
    _FakeGarmin.mfa_required = False


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

    def test_read_only_resume_does_not_repair_but_publishes_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir()
        garth_home.chmod(0o755)
        (garth_home / "garmin_tokens.json").write_text('{"di_token":"abc"}')
        monkeypatch.setattr(backend, "Garmin", _FakeGarmin)

        backend.resume(str(garth_home), read_only=True)

        # Published so later endpoint calls use (and refresh) this one client.
        assert backend._backend is _FakeGarmin.instances[0]
        assert stat.S_IMODE(garth_home.stat().st_mode) == 0o755

    def test_read_only_resume_refuses_symlinked_home(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir(mode=0o700)
        (tmp_path / "garth").symlink_to(real)

        with pytest.raises(GarminCliError, match="symlink"):
            backend.resume(str(tmp_path / "garth"), read_only=True)

    @pytest.mark.parametrize("read_only", [True, False])
    def test_resume_refuses_symlinked_token_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, read_only: bool
    ) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        (tmp_path / "real.json").write_text('{"di_token":"abc"}')
        (garth_home / "garmin_tokens.json").symlink_to(tmp_path / "real.json")
        monkeypatch.setattr(backend, "Garmin", _FakeGarmin)

        with pytest.raises(OSError, match="symlink"):
            backend.resume(str(garth_home), read_only=read_only)
        assert backend._backend is None


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

        client = backend.login("user@example.com", "secret", garth_home=str(garth_home))

        instance = _FakeGarmin.instances[0]
        assert client is instance
        assert instance.login_calls == [None]
        assert instance.garmintokens_env_at_login is None
        assert backend._backend is None  # published only by save()

    def test_login_returns_pending_mfa_when_challenged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        monkeypatch.setattr(backend, "Garmin", _FakeGarmin)
        _FakeGarmin.mfa_required = True

        pending = backend.login(
            "user@example.com", "secret", garth_home=str(garth_home), return_on_mfa=True
        )

        assert isinstance(pending, backend.PendingMFA)
        assert pending.client_state == {"signin_params": "opaque"}
        assert pending.garth_home == str(garth_home)
        assert backend._backend is None  # not activated until MFA completes

    def test_login_without_mfa_challenge_returns_client_and_reloads_profile(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        monkeypatch.setattr(backend, "Garmin", _FakeGarmin)

        result = backend.login(
            "user@example.com", "secret", garth_home=str(garth_home), return_on_mfa=True
        )

        instance = _FakeGarmin.instances[0]
        assert result is instance
        # Second login call replays from in-memory tokens to load the
        # profile/settings that upstream's return_on_mfa mode skips.
        assert len(instance.login_calls) == 2
        assert instance.login_calls[1] is not None

    def test_resume_mfa_login_returns_client_for_save(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        monkeypatch.setattr(backend, "Garmin", _FakeGarmin)
        _FakeGarmin.mfa_required = True

        pending = backend.login(
            "user@example.com", "secret", garth_home=str(garth_home), return_on_mfa=True
        )
        assert isinstance(pending, backend.PendingMFA)
        client = backend.resume_mfa_login(pending, "123456")

        instance = _FakeGarmin.instances[0]
        assert instance.resume_login_calls == [({"signin_params": "opaque"}, "123456")]
        assert client is instance
        assert backend._backend is None  # published only by save()

    def test_resume_rejects_legacy_tokens_without_new_tokenstore(self, tmp_path: Path) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        (garth_home / "oauth1_token.json").write_text("{}")
        (garth_home / "oauth2_token.json").write_text("{}")

        with pytest.raises(FileNotFoundError, match="No garmin_tokens.json"):
            backend.resume(str(garth_home))


class TestSave:
    def test_save_creates_secure_directory_and_token_file(self, tmp_path: Path) -> None:
        garth_home = tmp_path / "garth"
        fake = SimpleNamespace(client=_FakeClient())

        backend.save(str(garth_home), fake)  # type: ignore[arg-type]

        token_file = garth_home / "garmin_tokens.json"
        assert token_file.exists()
        assert stat.S_IMODE(garth_home.stat().st_mode) == 0o700
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
        assert backend._backend is fake

    def test_save_persists_the_login_client_not_a_concurrently_resumed_one(
        self, tmp_path: Path
    ) -> None:
        fresh = SimpleNamespace(client=_FakeClient())
        stale = SimpleNamespace(client=_FakeClient())
        # A status check's read-only resume published a stale client between
        # the login finishing and its session being saved.
        backend._backend = stale  # type: ignore[assignment]

        backend.save(str(tmp_path / "garth"), fresh)  # type: ignore[arg-type]

        assert fresh.client.dump_calls and not stale.client.dump_calls
        assert backend._backend is fresh  # published after saving

    def test_save_refuses_dangling_token_symlink(self, tmp_path: Path) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        (garth_home / "garmin_tokens.json").symlink_to(tmp_path / "missing.json")
        fake = SimpleNamespace(client=_FakeClient())

        with pytest.raises(OSError, match="symlink"):
            backend.save(str(garth_home), fake)  # type: ignore[arg-type]
        assert not fake.client.dump_calls
        assert backend._backend is None


class TestTypedWriteWrappers:
    """The new typed wrappers delegate to the upstream client verbatim."""

    def test_update_workout_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MagicMock()
        monkeypatch.setattr(backend, "_backend", client)

        backend.update_workout(12345, {"workoutName": "Tempo"})

        client.update_workout.assert_called_once_with(12345, {"workoutName": "Tempo"})

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

        def get_api_headers(self) -> dict[str, str]:
            return {}

        def _run_request(self, method: str, path: str, **kwargs: Any) -> None:
            return None

        def _refresh_session(self) -> None:
            self.refresh_calls += 1
            self.entered.set()
            assert self.release.wait(timeout=10)

    class _UpstreamInner:
        """Mimics garminconnect 0.3.20: a 401 refreshes under ``_token_lock``."""

        def __init__(self, threads: int, before_headers: Any = None) -> None:
            self._token_lock = threading.RLock()
            self._all_got_401 = threading.Barrier(threads)
            self._before_headers = before_headers
            self.refresh_calls = 0

        def get_api_headers(self) -> dict[str, str]:
            return {}

        def _run_request(self, method: str, path: str, **kwargs: Any) -> str:
            if self._before_headers is not None:
                self._before_headers()
            self.get_api_headers()  # the token actually sent
            self._all_got_401.wait(timeout=10)
            with self._token_lock:
                self._refresh_session()
            return "ok"

        def _refresh_session(self) -> None:
            self.refresh_calls += 1

    def test_concurrent_401s_refresh_once_under_upstream_token_lock(self) -> None:
        inner = self._UpstreamInner(threads=4)
        backend._serialize_refresh(SimpleNamespace(client=inner))

        threads = [threading.Thread(target=inner._run_request, args=("GET", "/x")) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert inner.refresh_calls == 1

    def test_401_on_a_token_refreshed_before_send_still_refreshes(self) -> None:
        """A request that waited out another thread's refresh sends the new
        token; if that token is rejected too, it must refresh again."""
        holder: dict[str, Any] = {}

        def other_thread_refreshes_first() -> None:
            other = threading.Thread(target=holder["inner"]._refresh_session)
            other.start()
            other.join(timeout=10)

        inner = self._UpstreamInner(threads=1, before_headers=other_thread_refreshes_first)
        holder["inner"] = inner
        backend._serialize_refresh(SimpleNamespace(client=inner))

        inner._run_request("GET", "/x")

        assert inner.refresh_calls == 2

    def test_stale_request_snapshot_does_not_suppress_a_later_direct_refresh(self) -> None:
        inner = self._UpstreamInner(threads=1)
        backend._serialize_refresh(SimpleNamespace(client=inner))

        inner._run_request("GET", "/x")  # refresh #1 inside a request
        inner._refresh_session()  # direct call, e.g. upstream login path

        assert inner.refresh_calls == 2

    def test_direct_refresh_leaves_no_snapshot_behind(self) -> None:
        inner = self._UpstreamInner(threads=1)
        backend._serialize_refresh(SimpleNamespace(client=inner))

        inner._refresh_session()  # direct call on this thread
        other = threading.Thread(target=inner._refresh_session)
        other.start()
        other.join(timeout=10)
        inner._refresh_session()  # must not compare against a stale snapshot

        assert inner.refresh_calls == 3

    def test_sequential_refreshes_both_run(self) -> None:
        inner = self._RefreshInner()
        inner.release.set()
        backend._serialize_refresh(SimpleNamespace(client=inner))

        inner._refresh_session()
        assert inner.refresh_calls == 1
        inner._refresh_session()
        assert inner.refresh_calls == 2
        assert inner._generation == 2


class TestProfileToday:
    """``profile_today`` follows the Garmin profile timezone, best effort."""

    def test_none_without_an_active_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(backend, "_backend", None)
        assert backend.profile_today() is None

    def test_uses_the_profile_timezone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        client = MagicMock()
        # UTC+14: differs from the host date for most of every UTC day.
        client.get_user_timezone.return_value = "Pacific/Kiritimati"
        monkeypatch.setattr(backend, "_backend", client)

        assert backend.profile_today() == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()

    @pytest.mark.parametrize("timezone", [None, "", "Not/AZone"])
    def test_none_when_timezone_unknown_or_invalid(
        self, monkeypatch: pytest.MonkeyPatch, timezone: Any
    ) -> None:
        client = MagicMock()
        client.get_user_timezone.return_value = timezone
        monkeypatch.setattr(backend, "_backend", client)
        assert backend.profile_today() is None

    def test_none_when_timezone_lookup_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MagicMock()
        client.get_user_timezone.side_effect = RuntimeError("network down")
        monkeypatch.setattr(backend, "_backend", client)
        assert backend.profile_today() is None


class TestSingleRetryLayer:
    """``_retry_loop`` is the only retry layer: upstream retries are disabled."""

    def test_login_and_resume_clients_disable_upstream_retries(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        (garth_home / "garmin_tokens.json").write_text('{"di_token":"abc"}')
        monkeypatch.setattr(backend, "Garmin", _FakeGarmin)

        backend.login("user@example.com", "secret", garth_home=str(garth_home))
        backend.resume(str(garth_home))

        assert [g.retry_attempts for g in _FakeGarmin.instances] == [0, 0]

    def test_failing_503_read_makes_one_attempt_per_retry_slot(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import garminconnect
        from garminconnect.client import Client

        from garmin_cli.endpoints._base import _make_request

        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        (garth_home / "garmin_tokens.json").write_text('{"di_token":"abc"}')
        monkeypatch.setattr(garminconnect.Garmin, "login", lambda self, tokenstore=None: None)
        monkeypatch.setattr(Client, "get_api_headers", lambda self: {})
        monkeypatch.setenv("GARMIN_CLI_RETRY_DELAYS", "1,2,3")
        monkeypatch.setattr("time.sleep", lambda _s: None)
        backend.resume(str(garth_home))
        session_request = MagicMock(return_value=MagicMock(status_code=503))
        monkeypatch.setattr(backend._require_backend().client._api_session, "request", session_request)

        with pytest.raises(GarminCliError) as exc_info:
            _make_request(backend.connectapi, "/usersummary-service/stats/steps/daily/a/b")

        assert exc_info.value.error_code == "SERVER_ERROR"
        assert session_request.call_count == 1 + 3


class TestRefreshFailureSurfacing:
    """Upstream swallows a failed token refresh and replays the 401; report the cause."""

    @pytest.mark.parametrize(
        ("refresh", "kind"),
        [
            (requests.ConnectTimeout("refresh timed out"), "unreachable"),
            (MagicMock(ok=False, status_code=503, text="down"), "server"),
            (MagicMock(ok=False, status_code=400, text="invalid_grant"), "rejected"),
        ],
    )
    def test_401_after_failed_refresh_is_classified_by_the_refresh(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, refresh: Any, kind: str
    ) -> None:
        import garminconnect
        from garminconnect.client import Client

        from garmin_cli.exceptions import failure_kind

        def _di_token_post(self: Any, *_args: Any) -> Any:
            if isinstance(refresh, Exception):
                raise refresh
            return refresh

        garth_home = tmp_path / "garth"
        garth_home.mkdir(mode=0o700)
        (garth_home / "garmin_tokens.json").write_text('{"di_token":"abc"}')
        monkeypatch.setattr(garminconnect.Garmin, "login", lambda self, tokenstore=None: None)
        monkeypatch.setattr(Client, "get_api_headers", lambda self: {})
        monkeypatch.setattr(Client, "_token_expires_soon", lambda self: False)
        monkeypatch.setattr(Client, "_di_token_post", _di_token_post)
        backend.resume(str(garth_home))
        inner = backend._require_backend().client
        inner.di_token, inner.di_refresh_token, inner.di_client_id = "token", "refresh", "client"
        monkeypatch.setattr(
            inner._api_session, "request", MagicMock(return_value=MagicMock(status_code=401))
        )

        with pytest.raises(Exception) as exc_info:
            backend.connectapi("/calendar-service/year/2026/month/0/day/1/start/1")

        assert failure_kind(exc_info.value) == kind
