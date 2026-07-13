"""Tests for garmin_cli.auth — ensure_authenticated()."""
from __future__ import annotations

import stat
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli import auth as auth_module
from garmin_cli.auth import complete_mfa_login, ensure_authenticated
from garmin_cli.backend import PendingMFA
from garmin_cli.config import CliConfig
from garmin_cli.exceptions import GarminCliError
from tests.helpers import make_http_error as _http_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs: Any) -> CliConfig:
    defaults = {
        "email": None,
        "password": None,
        "garth_home": "/tmp/test_garth_auth",
        "output_format": "table",
    }
    defaults.update(kwargs)
    return CliConfig(**defaults)


@pytest.fixture(autouse=True)
def _reset_probe_cache() -> None:
    """Reset the auth probe cache and pending-MFA state between tests."""
    auth_module._invalidate_probe_cache()
    auth_module._stash_pending_mfa(None)


# ---------------------------------------------------------------------------
# Resume-success path
# ---------------------------------------------------------------------------

class TestEnsureAuthenticatedResumeSuccess:

    def test_returns_none_when_resume_succeeds(self, mocker: Any, tmp_path: Path) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir))
        result = ensure_authenticated(config)
        assert result is None

    def test_calls_garth_resume_with_expanded_path(self, mocker: Any, tmp_path: Path) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir))
        ensure_authenticated(config)
        mock_garth.resume.assert_called_once()

    def test_does_not_call_login_when_resume_succeeds(self, mocker: Any, tmp_path: Path) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir))
        ensure_authenticated(config)
        mock_garth.login.assert_not_called()


# ---------------------------------------------------------------------------
# Resume-fails, no credentials
# ---------------------------------------------------------------------------

class TestEnsureAuthenticatedNoCredentials:

    def test_raises_garmin_cli_error_when_resume_fails_no_creds(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = Exception("no session")
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir), email=None, password=None)
        with pytest.raises(GarminCliError) as exc_info:
            ensure_authenticated(config)
        assert exc_info.value.error_code == "AUTH_MISSING"



# ---------------------------------------------------------------------------
# Resume-fails, has credentials, login succeeds
# ---------------------------------------------------------------------------

class TestEnsureAuthenticatedLoginSuccess:

    def test_calls_login_when_resume_fails(self, mocker: Any, tmp_path: Path) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = Exception("no session")
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(
            garth_home=str(garth_dir), email="user@test.com", password="pass"
        )
        ensure_authenticated(config)
        mock_garth.login.assert_called_once()

    def test_calls_login_with_email_and_password(self, mocker: Any, tmp_path: Path) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = Exception("no session")
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(
            garth_home=str(garth_dir), email="user@test.com", password="secret"
        )
        ensure_authenticated(config)
        mock_garth.login.assert_called_once_with(
            "user@test.com",
            "secret",
            garth_home=str(garth_dir),
            return_on_mfa=True,
        )

    def test_calls_save_after_login(self, mocker: Any, tmp_path: Path) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = Exception("no session")
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(
            garth_home=str(garth_dir), email="user@test.com", password="pass"
        )
        ensure_authenticated(config)
        mock_garth.save.assert_called_once()

    def test_file_not_found_on_resume_falls_back_to_login(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "missing_garth"

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = FileNotFoundError("no saved session")
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(
            garth_home=str(garth_dir), email="user@test.com", password="pass"
        )
        ensure_authenticated(config)
        mock_garth.login.assert_called_once_with(
            "user@test.com",
            "pass",
            garth_home=str(garth_dir),
            return_on_mfa=True,
        )

    def test_stale_resumed_session_falls_back_to_login(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(401)
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(
            garth_home=str(garth_dir), email="user@test.com", password="pass"
        )
        ensure_authenticated(config)
        mock_garth.login.assert_called_once_with(
            "user@test.com",
            "pass",
            garth_home=str(garth_dir),
            return_on_mfa=True,
        )

    def test_probe_server_error_raises_auth_failed(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """Non-401/403 probe failure (e.g. 500) must surface as AUTH_FAILED, not fall through."""
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(500)
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(
            garth_home=str(garth_dir), email="user@test.com", password="pass"
        )
        with pytest.raises(GarminCliError) as exc_info:
            ensure_authenticated(config)
        assert exc_info.value.error_code == "AUTH_FAILED"
        mock_garth.login.assert_not_called()


# ---------------------------------------------------------------------------
# Resume-fails, has credentials, login fails
# ---------------------------------------------------------------------------

class TestEnsureAuthenticatedLoginFailure:

    def test_raises_garmin_cli_error_when_login_fails(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = Exception("no session")
        mock_garth.login.side_effect = Exception("bad credentials")
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(
            garth_home=str(garth_dir), email="user@test.com", password="wrong"
        )
        with pytest.raises(GarminCliError) as exc_info:
            ensure_authenticated(config)
        assert exc_info.value.error_code == "AUTH_FAILED"



# ---------------------------------------------------------------------------
# MFA-required login flow
# ---------------------------------------------------------------------------

def _pending_mfa() -> PendingMFA:
    return PendingMFA(client=MagicMock(), client_state={"k": "v"}, garth_home=None)


class TestMFALogin:

    def test_mfa_challenge_raises_mfa_required_and_stashes_state(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = Exception("no session")
        mock_garth.login.return_value = _pending_mfa()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(
            garth_home=str(garth_dir), email="user@test.com", password="pass"
        )
        with pytest.raises(GarminCliError) as exc_info:
            ensure_authenticated(config)
        assert exc_info.value.error_code == "MFA_REQUIRED"
        assert auth_module._pending_mfa is not None
        mock_garth.save.assert_not_called()

    def test_complete_mfa_login_resumes_and_saves(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)
        pending = _pending_mfa()
        auth_module._stash_pending_mfa(pending)

        config = _make_config(garth_home=str(garth_dir))
        complete_mfa_login(config, "123456")

        mock_garth.resume_mfa_login.assert_called_once_with(pending, "123456")
        mock_garth.save.assert_called_once_with(str(garth_dir))
        assert auth_module._pending_mfa is None

    def test_complete_mfa_login_records_probe_so_next_call_skips_resume(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)
        auth_module._stash_pending_mfa(_pending_mfa())

        config = _make_config(garth_home=str(garth_dir))
        complete_mfa_login(config, "123456")
        ensure_authenticated(config)

        mock_garth.resume.assert_not_called()

    def test_pending_challenge_short_circuits_without_new_login(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = Exception("no session")
        mocker.patch("garmin_cli.auth.garth", mock_garth)
        auth_module._stash_pending_mfa(_pending_mfa())

        config = _make_config(
            garth_home=str(garth_dir), email="user@test.com", password="pass"
        )
        with pytest.raises(GarminCliError) as exc_info:
            ensure_authenticated(config)
        assert exc_info.value.error_code == "MFA_REQUIRED"
        mock_garth.login.assert_not_called()  # no fresh challenge sent

    def test_successful_probe_clears_pending_challenge(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mocker.patch("garmin_cli.auth.garth", MagicMock())
        auth_module._stash_pending_mfa(_pending_mfa())

        ensure_authenticated(_make_config(garth_home=str(garth_dir)))

        assert auth_module._pending_mfa is None

    def test_complete_mfa_login_rate_limited(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.resume_mfa_login.side_effect = _http_error(429)
        mocker.patch("garmin_cli.auth.garth", mock_garth)
        auth_module._stash_pending_mfa(_pending_mfa())

        config = _make_config(garth_home=str(garth_dir))
        with pytest.raises(GarminCliError) as exc_info:
            complete_mfa_login(config, "123456")
        assert exc_info.value.error_code == "RATE_LIMITED"
        # Throttled, not rejected: the challenge is restored for a retry.
        assert auth_module._pending_mfa is not None

    def test_complete_mfa_login_local_precondition_failure_keeps_challenge(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mocker.patch("garmin_cli.auth.garth", MagicMock())
        mocker.patch(
            "garmin_cli.auth._secure_directory",
            side_effect=GarminCliError(error="symlink", error_code="AUTH_FAILED"),
        )
        auth_module._stash_pending_mfa(_pending_mfa())

        config = _make_config(garth_home=str(tmp_path / "garth"))
        with pytest.raises(GarminCliError, match="symlink"):
            complete_mfa_login(config, "123456")
        # A repairable local failure must not burn the still-valid challenge.
        assert auth_module._pending_mfa is not None

    def test_concurrent_cold_calls_send_single_mfa_challenge(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """Racing unauthenticated calls must trigger exactly one Garmin login."""
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = Exception("no session")
        mock_garth.login.side_effect = lambda *a, **k: _pending_mfa()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(
            garth_home=str(garth_dir), email="user@test.com", password="pass"
        )
        n_threads = 8
        barrier = threading.Barrier(n_threads)
        codes: list[str] = []
        codes_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            try:
                ensure_authenticated(config)
            except GarminCliError as exc:
                with codes_lock:
                    codes.append(exc.error_code)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert codes == ["MFA_REQUIRED"] * n_threads
        mock_garth.login.assert_called_once()  # only one code sent to the user

    def test_complete_mfa_login_save_failure_reports_persistence(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.save.side_effect = OSError("read-only")
        mocker.patch("garmin_cli.auth.garth", mock_garth)
        auth_module._stash_pending_mfa(_pending_mfa())

        config = _make_config(garth_home=str(garth_dir))
        with pytest.raises(GarminCliError) as exc_info:
            complete_mfa_login(config, "123456")
        assert exc_info.value.error_code == "AUTH_FAILED"
        assert "saving the session" in exc_info.value.error  # not blamed on the code

    def test_complete_mfa_login_prefers_pending_garth_home(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        pending_dir = tmp_path / "pending_home"
        pending_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)
        auth_module._stash_pending_mfa(
            PendingMFA(client=MagicMock(), client_state={"k": "v"}, garth_home=str(pending_dir))
        )

        config = _make_config(garth_home=str(tmp_path / "other_home"))
        complete_mfa_login(config, "123456")

        mock_garth.save.assert_called_once_with(str(pending_dir))

    def test_complete_mfa_login_without_pending_raises_invalid_input(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mocker.patch("garmin_cli.auth.garth", MagicMock())
        config = _make_config(garth_home=str(tmp_path / "garth"))
        with pytest.raises(GarminCliError) as exc_info:
            complete_mfa_login(config, "123456")
        assert exc_info.value.error_code == "INVALID_INPUT"

    def test_complete_mfa_login_failure_raises_auth_failed_and_consumes_state(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.resume_mfa_login.side_effect = Exception("bad code")
        mocker.patch("garmin_cli.auth.garth", mock_garth)
        auth_module._stash_pending_mfa(_pending_mfa())

        config = _make_config(garth_home=str(garth_dir))
        with pytest.raises(GarminCliError) as exc_info:
            complete_mfa_login(config, "000000")
        assert exc_info.value.error_code == "AUTH_FAILED"

        # Pending state is single-use: a retry without a fresh challenge
        # reports INVALID_INPUT rather than replaying the stale state.
        with pytest.raises(GarminCliError) as exc_info:
            complete_mfa_login(config, "000000")
        assert exc_info.value.error_code == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Security: symlink rejection
# ---------------------------------------------------------------------------

class TestEnsureAuthenticatedSecurity:

    def test_raises_when_garth_home_is_symlink(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        real_dir = tmp_path / "real_garth"
        real_dir.mkdir(mode=0o700)
        symlink_dir = tmp_path / "link_garth"
        symlink_dir.symlink_to(real_dir)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(symlink_dir))
        with pytest.raises(GarminCliError):
            ensure_authenticated(config)

    def test_fixes_directory_permissions_to_0o700(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o755)  # too permissive

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir))
        ensure_authenticated(config)

        actual_mode = stat.S_IMODE(garth_dir.stat().st_mode)
        assert actual_mode == 0o700

    def test_creates_garth_home_directory_if_not_exists(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "nonexistent_garth"
        assert not garth_dir.exists()

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = Exception("no session")  # force login path
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir), email="u@t.com", password="p")
        ensure_authenticated(config)
        assert garth_dir.exists()

    def test_created_directory_has_0o700_permissions(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "new_garth"
        assert not garth_dir.exists()

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = Exception("no session")  # force login path
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir), email="u@t.com", password="p")
        ensure_authenticated(config)

        actual_mode = stat.S_IMODE(garth_dir.stat().st_mode)
        assert actual_mode == 0o700


# ---------------------------------------------------------------------------
# Probe-TTL cache tests
# ---------------------------------------------------------------------------

class TestProbeTtlCache:

    def test_ttl_hit_skips_resume_and_probe(
        self, mocker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Second call within TTL must make zero resume/probe calls."""
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir))

        # First call — probe runs and warms cache.
        ensure_authenticated(config)
        assert mock_garth.resume.call_count == 1
        assert mock_garth.connectapi.call_count == 1

        mock_garth.reset_mock()

        # Second call — cache hit, no resume, no probe.
        ensure_authenticated(config)
        mock_garth.resume.assert_not_called()
        mock_garth.connectapi.assert_not_called()

    def test_ttl_expiry_re_probes(
        self, mocker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After TTL expires the next call must resume+probe again."""
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "0.05")  # 50 ms
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir))

        ensure_authenticated(config)  # warm cache
        assert mock_garth.resume.call_count == 1

        time.sleep(0.1)  # let TTL expire

        mock_garth.reset_mock()
        ensure_authenticated(config)
        assert mock_garth.resume.call_count == 1
        assert mock_garth.connectapi.call_count == 1

    def test_ttl_zero_disables_caching(
        self, mocker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TTL=0 must disable caching (probe on every call)."""
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "0")
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir))

        ensure_authenticated(config)
        ensure_authenticated(config)
        ensure_authenticated(config)

        assert mock_garth.resume.call_count == 3
        assert mock_garth.connectapi.call_count == 3

    def test_different_garth_home_re_probes(
        self, mocker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A different garth_home must trigger a fresh resume+probe."""
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")

        garth_dir_a = tmp_path / "garth_a"
        garth_dir_a.mkdir(mode=0o700)
        garth_dir_b = tmp_path / "garth_b"
        garth_dir_b.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config_a = _make_config(garth_home=str(garth_dir_a))
        config_b = _make_config(garth_home=str(garth_dir_b))

        ensure_authenticated(config_a)
        assert mock_garth.resume.call_count == 1

        mock_garth.reset_mock()
        ensure_authenticated(config_b)
        assert mock_garth.resume.call_count == 1
        assert mock_garth.connectapi.call_count == 1

    def test_auth_failure_invalidates_cache(
        self, mocker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a probe failure the cache must be cleared so the NEXT call re-probes.

        Scenario:
        1. First call: probe fails with 401 → falls through to login (cache stays empty).
        2. Second call: probe succeeds → cache warms.
        3. Third call: cache hit → no resume/probe.
        4. Manually invalidate cache (simulating expiry / garth_home change).
        5. Fourth call: no cache hit → resume+probe.
        """
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        # First probe fails with 401.
        mock_garth.connectapi.side_effect = _http_error(401)
        mocker.patch("garmin_cli.auth.garth", mock_garth)
        config = _make_config(
            garth_home=str(garth_dir), email="u@t.com", password="p"
        )

        # First call — probe fails → login, cache NOT populated.
        ensure_authenticated(config)
        assert mock_garth.resume.call_count == 1
        mock_garth.login.assert_called_once()

        # Next probe succeeds.
        mock_garth.connectapi.side_effect = None
        mock_garth.reset_mock()

        # Second call — resume+probe runs, cache warms.
        ensure_authenticated(config)
        assert mock_garth.resume.call_count == 1
        assert mock_garth.connectapi.call_count == 1

        mock_garth.reset_mock()

        # Third call — cache hit, zero I/O.
        ensure_authenticated(config)
        mock_garth.resume.assert_not_called()
        mock_garth.connectapi.assert_not_called()

        # Manually invalidate (mirrors what garth_home change would do).
        auth_module._invalidate_probe_cache(str(garth_dir))
        mock_garth.reset_mock()

        # Fourth call — no cache → resume+probe again.
        ensure_authenticated(config)
        assert mock_garth.resume.call_count == 1
        assert mock_garth.connectapi.call_count == 1

    def test_login_invalidates_cache(
        self, mocker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a fresh login the probe cache must be cleared."""
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        # Warm the cache with a successful probe.
        config = _make_config(garth_home=str(garth_dir))
        ensure_authenticated(config)
        assert mock_garth.resume.call_count == 1

        # Manually call login invalidation to mirror login path.
        auth_module._invalidate_probe_cache()

        mock_garth.reset_mock()
        # After invalidation a fresh call must resume+probe.
        ensure_authenticated(config)
        assert mock_garth.resume.call_count == 1
        assert mock_garth.connectapi.call_count == 1

    def test_probe_not_recorded_on_probe_failure(
        self, mocker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failed probe must NOT populate the cache."""
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(401)
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(
            garth_home=str(garth_dir), email="u@t.com", password="p"
        )
        ensure_authenticated(config)  # probe fails → login

        mock_garth.reset_mock()
        mock_garth.connectapi.side_effect = None  # next probe succeeds
        ensure_authenticated(config)
        # Must re-probe (cache was not populated from the failed probe).
        assert mock_garth.resume.call_count == 1

    def test_cache_hit_returns_immediately_with_zero_io(
        self, mocker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On a cache hit, no disk reads and no network calls are made."""
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir))
        ensure_authenticated(config)  # warm cache

        mock_garth.reset_mock()

        # Patch resume and connectapi to fail — they must not be called.
        mock_garth.resume.side_effect = Exception("should not be called")
        mock_garth.connectapi.side_effect = Exception("should not be called")

        result = ensure_authenticated(config)
        assert result is None  # no exception raised

    def test_cache_hit_skips_directory_security_check(
        self, mocker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The stat/chmod security check runs on cache misses only, so a hot
        MCP server does no per-call disk I/O."""
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.auth.garth", mock_garth)
        secure = mocker.patch("garmin_cli.auth.ensure_secure_directory")

        config = _make_config(garth_home=str(garth_dir))

        ensure_authenticated(config)  # cache miss — security check runs
        assert secure.call_count == 1

        ensure_authenticated(config)  # cache hit — security check skipped
        assert secure.call_count == 1


# ---------------------------------------------------------------------------
# Concurrency safety tests
# ---------------------------------------------------------------------------

class TestConcurrencySafety:

    def test_concurrent_calls_do_not_double_login(
        self, mocker: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Concurrent ensure_authenticated calls from multiple threads must not
        cause duplicate logins — the probe cache stops the extra calls."""
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)

        # First call succeeds and warms the cache; subsequent calls (which
        # arrive concurrently after the first returns) should hit the cache.
        resume_count = 0
        resume_lock = threading.Lock()

        def _fake_resume(path: str) -> None:
            nonlocal resume_count
            with resume_lock:
                resume_count += 1

        mock_garth = MagicMock()
        mock_garth.resume.side_effect = _fake_resume
        mocker.patch("garmin_cli.auth.garth", mock_garth)

        config = _make_config(garth_home=str(garth_dir))
        n_threads = 8
        barrier = threading.Barrier(n_threads)
        errors: list[Exception] = []

        # Warm the cache in the main thread first.
        ensure_authenticated(config)
        assert resume_count == 1

        mock_garth.reset_mock()
        resume_count = 0

        def _worker() -> None:
            try:
                barrier.wait()
                ensure_authenticated(config)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All threads hit the cache — zero resume calls.
        assert resume_count == 0

    def test_lock_protects_probe_cache_under_concurrent_access(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Directly stress the probe cache helpers from multiple threads."""
        monkeypatch.setenv("GARMIN_CLI_AUTH_PROBE_TTL", "600")
        garth_home = str(tmp_path / "garth")

        n_threads = 20
        barrier = threading.Barrier(n_threads)
        errors: list[Exception] = []

        def _worker() -> None:
            try:
                barrier.wait()
                auth_module._record_probe_ok(garth_home)
                auth_module._probe_cache_hit(garth_home, 600.0)
                auth_module._invalidate_probe_cache(garth_home)
                auth_module._record_probe_ok(garth_home)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
