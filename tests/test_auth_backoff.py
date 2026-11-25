"""Tests for the failed-login backoff and login-lock waiter re-check in auth."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from garmin_cli import auth as auth_module
from garmin_cli import login_backoff
from garmin_cli.auth import complete_mfa_login, ensure_authenticated
from garmin_cli.backend import PendingMFA
from garmin_cli.config import CliConfig
from garmin_cli.exceptions import GarminCliError
from tests.helpers import make_http_error as _http_error


@pytest.fixture(autouse=True)
def _reset_auth_state() -> None:
    auth_module._invalidate_probe_cache()
    auth_module._stash_pending_mfa(None)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1000.0]
    monkeypatch.setattr(login_backoff, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


@pytest.fixture
def garth(mocker: Any) -> MagicMock:
    mock_garth = MagicMock()
    mock_garth.resume.side_effect = Exception("no session")
    mock_garth.login.side_effect = GarminConnectAuthenticationError("bad credentials")
    mocker.patch("garmin_cli.auth.garth", mock_garth)
    return mock_garth


def _config(tmp_path: Path, password: str = "wrong", home: str = "garth") -> CliConfig:
    path = tmp_path / home
    path.mkdir(mode=0o700, exist_ok=True)
    return CliConfig(email="user@test.com", password=password, garth_home=str(path))


def _auth_error(config: CliConfig) -> GarminCliError:
    with pytest.raises(GarminCliError) as exc_info:
        ensure_authenticated(config)
    return exc_info.value


def _pending() -> PendingMFA:
    return PendingMFA(client=MagicMock(), client_state={}, garth_home=None)


def test_failed_login_blocks_repeat_login_within_window(
    garth: MagicMock, clock: list[float], tmp_path: Path
) -> None:
    config = _config(tmp_path)
    first = _auth_error(config)
    clock[0] += 10
    second = _auth_error(config)

    assert first.error_code == second.error_code == "AUTH_FAILED"
    assert first.retry_after_seconds == 60  # the first failure reports its own wait
    assert second.retry_after_seconds == 50
    assert "50 seconds" in second.error
    garth.login.assert_called_once()


def test_rate_limited_login_is_cached_with_backoff_wait(
    garth: MagicMock, clock: list[float], tmp_path: Path
) -> None:
    garth.login.side_effect = _http_error(429)
    config = _config(tmp_path)

    first = _auth_error(config)

    assert first.error_code == "RATE_LIMITED"
    assert first.retry_after_seconds == 60  # not the generic retry delay
    assert _auth_error(config).error_code == "RATE_LIMITED"
    garth.login.assert_called_once()


def test_backoff_doubles_per_consecutive_failure_and_caps(
    garth: MagicMock, clock: list[float], tmp_path: Path
) -> None:
    config = _config(tmp_path)
    windows = []
    for _ in range(6):
        _auth_error(config)  # real login attempt, fails
        wait = _auth_error(config).retry_after_seconds  # blocked, same instant
        assert wait is not None
        windows.append(wait)
        clock[0] += wait

    assert windows == [60, 120, 240, 480, 900, 900]
    assert garth.login.call_count == 6


def test_huge_failure_count_does_not_overflow() -> None:
    failure = login_backoff._Failure("key", "x", "AUTH_FAILED", 0.0, 10_000)

    assert failure.backoff == 900


def test_success_resets_backoff(garth: MagicMock, clock: list[float], tmp_path: Path) -> None:
    config = _config(tmp_path)
    _auth_error(config)
    clock[0] += 60
    garth.login.side_effect = None
    garth.login.return_value = None
    ensure_authenticated(config)
    garth.login.side_effect = GarminConnectAuthenticationError("bad credentials")

    _auth_error(config)

    assert _auth_error(config).retry_after_seconds == 60  # count restarted


def test_successful_resume_clears_backoff(
    garth: MagicMock, clock: list[float], tmp_path: Path
) -> None:
    config = _config(tmp_path)
    _auth_error(config)
    garth.resume.side_effect = None  # e.g. `garmin-cli login` saved a session meanwhile

    ensure_authenticated(config)

    assert login_backoff._failure is None


def test_credential_change_resets_backoff(
    garth: MagicMock, clock: list[float], tmp_path: Path
) -> None:
    _auth_error(_config(tmp_path, password="old"))
    _auth_error(_config(tmp_path, password="new"))

    assert garth.login.call_count == 2


def test_wrong_mfa_code_does_not_trigger_immediate_new_login(
    garth: MagicMock, clock: list[float], tmp_path: Path
) -> None:
    config = _config(tmp_path)
    garth.resume_mfa_login.side_effect = GarminConnectAuthenticationError("Widget MFA failed")
    auth_module._stash_pending_mfa(_pending())
    with pytest.raises(GarminCliError) as rejected:
        complete_mfa_login(config, "000000")
    clock[0] += 15

    blocked = _auth_error(config)

    assert rejected.value.retry_after_seconds == 60
    assert "Wait 60 seconds" in rejected.value.error
    assert blocked.error_code == "AUTH_FAILED"
    assert blocked.retry_after_seconds == 45
    # One consistent instruction, not "retry now" plus "wait".
    assert blocked.error.startswith("The MFA code was rejected. Wait 45 seconds")
    assert "paused" not in blocked.error
    garth.login.assert_not_called()  # no fresh MFA code sent


def test_mfa_429_gates_resubmission_but_keeps_challenge(
    garth: MagicMock, clock: list[float], tmp_path: Path
) -> None:
    config = _config(tmp_path)
    garth.resume_mfa_login.side_effect = _http_error(429)
    auth_module._stash_pending_mfa(_pending())
    with pytest.raises(GarminCliError) as throttled:
        complete_mfa_login(config, "123456")

    with pytest.raises(GarminCliError) as gated:
        complete_mfa_login(config, "123456")

    assert throttled.value.error_code == "RATE_LIMITED"
    assert throttled.value.retry_after_seconds == 60
    assert gated.value.error_code == "RATE_LIMITED"
    garth.resume_mfa_login.assert_called_once()  # gated before reaching Garmin
    assert auth_module._has_pending_mfa()

    clock[0] += 60
    garth.resume_mfa_login.side_effect = None
    complete_mfa_login(config, "123456")
    assert not auth_module._has_pending_mfa()


def _wrapped_throttle() -> Exception:
    try:
        raise GarminConnectTooManyRequestsError("Too many login attempts")
    except GarminConnectTooManyRequestsError as inner:
        outer = RuntimeError("login failed")
        outer.__cause__ = inner
        return outer


def _upstream_timeout() -> Exception:
    """Upstream's wrapping of a transport timeout (``raise ... from e``)."""
    try:
        raise GarminConnectConnectionError("Connection error: Read timed out") from requests.Timeout("t")
    except GarminConnectConnectionError as exc:
        return exc


@pytest.mark.parametrize(
    ("exc", "code", "backs_off"),
    [
        (GarminConnectTooManyRequestsError("Too many login attempts"), "RATE_LIMITED", True),
        (_http_error(427), "RATE_LIMITED", True),
        (_wrapped_throttle(), "RATE_LIMITED", True),
        (GarminConnectAuthenticationError("Widget login failed"), "AUTH_FAILED", True),
        (_http_error(401), "AUTH_FAILED", True),
        (_http_error(403), "AUTH_FAILED", True),
        (_http_error(503), "SERVER_ERROR", False),
        (_upstream_timeout(), "NETWORK_ERROR", False),
        (GarminConnectConnectionError("curl_cffi not available"), "AUTH_FAILED", False),
        (ConnectionError("Connection refused"), "NETWORK_ERROR", False),
        (RuntimeError("unexpected SSO page"), "AUTH_FAILED", False),
    ],
)
def test_only_rejections_and_throttles_start_backoff(
    garth: MagicMock, clock: list[float], tmp_path: Path,
    exc: Exception, code: str, backs_off: bool,
) -> None:
    garth.login.side_effect = exc
    config = _config(tmp_path)

    first = _auth_error(config)
    _auth_error(config)

    assert first.error_code == code
    assert (first.retry_after_seconds is not None) is backs_off
    assert garth.login.call_count == (1 if backs_off else 2)
    if not backs_off:
        assert "credentials" not in first.error


def test_mfa_throttle_without_status_keeps_challenge(
    garth: MagicMock, clock: list[float], tmp_path: Path
) -> None:
    garth.resume_mfa_login.side_effect = GarminConnectTooManyRequestsError("slow down")
    auth_module._stash_pending_mfa(_pending())

    with pytest.raises(GarminCliError) as throttled:
        complete_mfa_login(_config(tmp_path), "123456")

    assert throttled.value.error_code == "RATE_LIMITED"
    assert auth_module._has_pending_mfa()


def test_login_saves_the_client_it_authenticated(garth: MagicMock, tmp_path: Path) -> None:
    fresh = MagicMock(name="fresh-client")
    garth.login.side_effect = None
    garth.login.return_value = fresh
    config = _config(tmp_path, password="right")

    ensure_authenticated(config)

    garth.save.assert_called_once_with(config.garth_home, fresh)


def test_home_key_ignores_trailing_slash(
    garth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
    garth.login.side_effect = None
    garth.login.return_value = MagicMock()
    plain = _config(tmp_path, password="right")
    slashed = CliConfig(email=plain.email, password=plain.password, garth_home=plain.garth_home + "/")
    auth_module._stash_pending_mfa(PendingMFA(client=MagicMock(), client_state={}, garth_home=None))

    complete_mfa_login(slashed, "123456")
    ensure_authenticated(plain)  # same home: probe-cache hit, no resume

    assert login_backoff.generation(plain.garth_home) == 1
    garth.resume.assert_not_called()


def test_waiter_reports_non_auth_probe_failure_instead_of_logging_in(
    garth: MagicMock, tmp_path: Path
) -> None:
    config = _config(tmp_path, password="right")
    _peer_logs_in_during_first_resume(garth, config.garth_home, later_resumes_work=True)
    garth.connectapi.side_effect = _http_error(500)

    with pytest.raises(GarminCliError) as exc_info:
        ensure_authenticated(config)

    assert exc_info.value.error_code == "SERVER_ERROR"
    garth.login.assert_not_called()


def _peer_logs_in_during_first_resume(
    garth: MagicMock, home: str, later_resumes_work: bool
) -> None:
    """First resume: a peer finishes logging in (generation bumps), ours fails."""
    calls = 0

    def _resume(_home: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            login_backoff.record_success(home)
            raise Exception("stale session")
        if not later_resumes_work:
            raise Exception("still no session")

    garth.resume.side_effect = _resume
    garth.login.side_effect = None
    garth.login.return_value = None


def test_waiter_re_resumes_peer_session_instead_of_logging_in(
    garth: MagicMock, tmp_path: Path
) -> None:
    config = _config(tmp_path, password="right")
    _peer_logs_in_during_first_resume(garth, config.garth_home, later_resumes_work=True)

    ensure_authenticated(config)

    garth.login.assert_not_called()
    assert garth.resume.call_count == 2  # re-resumed what the peer persisted
    assert garth.connectapi.call_count == 1  # and probed it


def test_waiter_reports_network_failure_on_peer_resume_instead_of_logging_in(
    garth: MagicMock, tmp_path: Path
) -> None:
    config = _config(tmp_path, password="right")
    calls = 0

    def _resume(_home: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            login_backoff.record_success(config.garth_home)
            raise Exception("stale session")
        raise requests.Timeout("profile load timed out")

    garth.resume.side_effect = _resume

    assert _auth_error(config).error_code == "NETWORK_ERROR"
    garth.login.assert_not_called()


def test_waiter_logs_in_when_peer_session_does_not_resume(
    garth: MagicMock, tmp_path: Path
) -> None:
    config = _config(tmp_path, password="right")
    _peer_logs_in_during_first_resume(garth, config.garth_home, later_resumes_work=False)

    ensure_authenticated(config)

    garth.login.assert_called_once()


def test_login_for_another_home_does_not_satisfy_waiter(
    garth: MagicMock, tmp_path: Path
) -> None:
    config = _config(tmp_path, password="right", home="b")
    other_home = str(tmp_path / "a")
    _peer_logs_in_during_first_resume(garth, other_home, later_resumes_work=True)

    ensure_authenticated(config)

    garth.login.assert_called_once()
    assert garth.resume.call_count == 1  # no re-check for an unrelated home


def test_concurrent_waiter_skips_second_login(garth: MagicMock, tmp_path: Path) -> None:
    config = _config(tmp_path, password="right")
    in_login = threading.Event()
    release = threading.Event()
    waiter_resumed = threading.Event()
    resume_calls = 0

    def _resume(_home: str) -> None:
        nonlocal resume_calls
        resume_calls += 1
        if resume_calls == 2:
            waiter_resumed.set()
        if resume_calls <= 2:
            raise Exception("no session")

    def _login(*_a: Any, **_k: Any) -> None:
        in_login.set()
        release.wait(5)

    garth.resume.side_effect = _resume
    garth.login.side_effect = _login
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            ensure_authenticated(config)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    first = threading.Thread(target=_worker)
    first.start()
    assert in_login.wait(5)
    second = threading.Thread(target=_worker)
    second.start()
    assert waiter_resumed.wait(5)
    release.set()
    first.join(5)
    second.join(5)

    assert not errors
    garth.login.assert_called_once()
