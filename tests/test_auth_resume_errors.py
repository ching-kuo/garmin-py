"""Classification of session resume, probe, login and MFA failures in garmin_cli.auth."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from garminconnect import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError

from garmin_cli import auth as auth_module
from garmin_cli.auth import complete_mfa_login, ensure_authenticated, probe_session_status
from garmin_cli.backend import PendingMFA
from garmin_cli.config import CliConfig
from garmin_cli.exceptions import GarminCliError
from tests.helpers import make_http_error as _http_error
from tests.helpers import make_requests_http_error


@pytest.fixture(autouse=True)
def _reset_auth_state() -> None:
    auth_module._invalidate_probe_cache()
    auth_module._stash_pending_mfa(None)


@pytest.fixture
def garth(mocker: Any) -> MagicMock:
    mock_garth = MagicMock()
    mocker.patch("garmin_cli.auth.garth", mock_garth)
    return mock_garth


def _config(tmp_path: Path, email: str | None = "user@test.com") -> CliConfig:
    home = tmp_path / "garth"
    home.mkdir(mode=0o700, exist_ok=True)
    return CliConfig(email=email, password="pass" if email else None, garth_home=str(home))


def _chained(outer: Exception, cause: BaseException) -> Exception:
    try:
        raise outer from cause
    except Exception as exc:
        return exc


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (_http_error(503), "SERVER_ERROR"),
        (_http_error(429), "RATE_LIMITED"),
        (GarminConnectTooManyRequestsError("returned 427"), "RATE_LIMITED"),
        (requests.Timeout("read timed out"), "NETWORK_ERROR"),
        (ValueError("unexpected payload"), "AUTH_FAILED"),
    ],
)
def test_probe_failure_is_classified_without_logging_in(
    garth: MagicMock, tmp_path: Path, exc: Exception, code: str
) -> None:
    """A throttled, failing, or unreachable probe is not a bad session: no re-login."""
    garth.connectapi.side_effect = exc

    with pytest.raises(GarminCliError) as exc_info:
        ensure_authenticated(_config(tmp_path))

    assert exc_info.value.error_code == code
    garth.login.assert_not_called()


@pytest.mark.parametrize("step", ["resume", "connectapi"])
@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (make_requests_http_error(503), "SERVER_ERROR"),
        (GarminConnectTooManyRequestsError("returned 427"), "RATE_LIMITED"),
        (requests.ConnectionError("refused"), "NETWORK_ERROR"),
        (requests.Timeout("read timed out"), "NETWORK_ERROR"),
        (make_requests_http_error(401), "AUTH_FAILED"),
        (PermissionError("denied"), "AUTH_FAILED"),
    ],
)
def test_status_probe_reports_classified_error_code(
    garth: MagicMock, tmp_path: Path, exc: Exception, code: str, step: str
) -> None:
    getattr(garth, step).side_effect = exc

    result = probe_session_status(_config(tmp_path))

    assert (result.authenticated, result.error_code) == (False, code)


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (make_requests_http_error(503), "SERVER_ERROR"),
        (make_requests_http_error(429), "RATE_LIMITED"),
        (requests.Timeout("profile load timed out"), "NETWORK_ERROR"),
        (
            _chained(
                GarminConnectAuthenticationError("Failed to retrieve social profile"),
                make_requests_http_error(502),
            ),
            "SERVER_ERROR",
        ),
        (PermissionError("denied"), "AUTH_FAILED"),
    ],
)
def test_resume_failure_is_classified_without_logging_in(
    garth: MagicMock, tmp_path: Path, exc: Exception, code: str
) -> None:
    """Resuming makes profile requests; their throttles/5xx/timeouts are not bad sessions."""
    garth.resume.side_effect = exc

    with pytest.raises(GarminCliError) as exc_info:
        ensure_authenticated(_config(tmp_path))

    assert exc_info.value.error_code == code
    garth.login.assert_not_called()


def test_resume_rejected_by_garmin_falls_back_to_login(garth: MagicMock, tmp_path: Path) -> None:
    garth.resume.side_effect = make_requests_http_error(401)

    ensure_authenticated(_config(tmp_path))

    garth.login.assert_called_once()


def test_login_validation_error_is_not_rewritten(garth: MagicMock, tmp_path: Path) -> None:
    garth.resume.side_effect = FileNotFoundError("no session")
    garth.login.side_effect = GarminCliError("Garmin home must be a directory.", "INVALID_INPUT")

    with pytest.raises(GarminCliError) as exc_info:
        ensure_authenticated(_config(tmp_path))

    assert (exc_info.value.error_code, exc_info.value.error) == (
        "INVALID_INPUT",
        "Garmin home must be a directory.",
    )


def test_peer_resume_validation_error_is_not_swallowed(garth: MagicMock, tmp_path: Path) -> None:
    garth.resume.side_effect = GarminCliError("Garmin home must be a directory.", "INVALID_INPUT")

    with pytest.raises(GarminCliError) as exc_info:
        auth_module._resumed_session_works(_config(tmp_path).garth_home)

    assert exc_info.value.error_code == "INVALID_INPUT"


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (_http_error(429), "RATE_LIMITED"),
        (_http_error(503), "SERVER_ERROR"),
        (requests.Timeout("read timed out"), "NETWORK_ERROR"),
    ],
)
def test_transient_mfa_failure_keeps_the_challenge(
    garth: MagicMock, tmp_path: Path, exc: Exception, code: str
) -> None:
    garth.resume_mfa_login.side_effect = exc
    auth_module._stash_pending_mfa(PendingMFA(client=MagicMock(), client_state={}, garth_home=None))

    with pytest.raises(GarminCliError) as exc_info:
        complete_mfa_login(_config(tmp_path), "123456")

    assert exc_info.value.error_code == code
    assert auth_module._has_pending_mfa()
