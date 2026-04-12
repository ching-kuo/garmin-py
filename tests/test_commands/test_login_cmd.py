"""CLI integration tests for login command using CliRunner."""
from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any
from unittest.mock import ANY
from unittest.mock import MagicMock

from click.testing import CliRunner

from garmin_cli.cli import cli
from tests.helpers import make_http_error as _http_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_login(
    args: list[str],
    mocker: Any,
    *,
    garth_side_effect: Exception | None = None,
    input: str | None = None,
    tmp_path: Path | None = None,
) -> Any:
    """Invoke the login command with a mocked garth module."""
    mock_garth = MagicMock()
    if garth_side_effect is not None:
        mock_garth.login.side_effect = garth_side_effect
    mocker.patch("garmin_cli.commands.login.garth", mock_garth)
    runner = CliRunner(mix_stderr=False)
    extra: dict[str, Any] = {}
    if input is not None:
        extra["input"] = input
    if tmp_path is not None:
        garth_dir = str(tmp_path / "garth")
        full_args = ["--garmin-home", garth_dir] + args
    else:
        full_args = args
    result = runner.invoke(cli, full_args, catch_exceptions=False, **extra)
    return result, mock_garth



# ---------------------------------------------------------------------------
# garmin-cli login — prompts and success path
# ---------------------------------------------------------------------------

class TestLoginCommand:

    def test_login_exits_zero_on_success(self, mocker: Any, tmp_path: Path) -> None:
        result, _ = _run_login(
            ["login"],
            mocker,
            input="user@example.com\npassword123\n",
            tmp_path=tmp_path,
        )
        assert result.exit_code == 0

    def test_login_calls_garth_login_with_email_and_password(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        result, mock_garth = _run_login(
            ["login"],
            mocker,
            input="user@example.com\nsecretpassword\n",
            tmp_path=tmp_path,
        )
        mock_garth.login.assert_called_once_with(
            "user@example.com",
            "secretpassword",
            garth_home=str(tmp_path / "garth"),
            prompt_mfa=ANY,
        )

    def test_login_calls_garth_save_after_login(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        result, mock_garth = _run_login(
            ["login"],
            mocker,
            input="user@example.com\nsecretpassword\n",
            tmp_path=tmp_path,
        )
        mock_garth.save.assert_called_once()

    def test_login_creates_garth_home_directory(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        assert not garth_dir.exists()
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        runner = CliRunner(mix_stderr=False)
        runner.invoke(
            cli,
            ["--garmin-home", str(garth_dir), "login"],
            input="user@example.com\nsecretpassword\n",
            catch_exceptions=False,
        )
        assert garth_dir.exists()

    def test_login_success_outputs_success_message(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        result, _ = _run_login(
            ["login"],
            mocker,
            input="user@example.com\nsecretpassword\n",
            tmp_path=tmp_path,
        )
        output = result.output.lower()
        assert "success" in output or "logged in" in output or "saved" in output

    def test_login_prompts_for_email(self, mocker: Any, tmp_path: Path) -> None:
        result, _ = _run_login(
            ["login"],
            mocker,
            input="user@example.com\npassword\n",
            tmp_path=tmp_path,
        )
        assert "email" in result.output.lower()

    def test_login_prompts_for_password(self, mocker: Any, tmp_path: Path) -> None:
        result, _ = _run_login(
            ["login"],
            mocker,
            input="user@example.com\npassword\n",
            tmp_path=tmp_path,
        )
        assert "password" in result.output.lower()

    def test_login_accepts_email_and_password_as_options(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """--email and --password options bypass the prompts."""
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = str(tmp_path / "garth")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            [
                "--garmin-home", garth_dir,
                "login",
                "--email", "cli@example.com",
                "--password", "clipass",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        mock_garth.login.assert_called_once_with(
            "cli@example.com",
            "clipass",
            garth_home=garth_dir,
            prompt_mfa=ANY,
        )

    def test_login_json_mode_without_credentials_returns_json_error(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        result, _ = _run_login(
            ["--json", "login"],
            mocker,
            tmp_path=tmp_path,
        )

        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_INPUT"

    def test_login_repairs_insecure_garth_home_permissions(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o755)

        result, mock_garth = _run_login(
            [
                "login",
                "--email", "cli@example.com",
                "--password", "clipass",
            ],
            mocker,
            tmp_path=tmp_path,
        )

        assert result.exit_code == 0
        assert stat.S_IMODE(garth_dir.stat().st_mode) == 0o700
        mock_garth.save.assert_called_once_with(str(garth_dir))

    def test_login_rejects_symlink_garth_home(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        target_dir = tmp_path / "target"
        target_dir.mkdir(mode=0o700)
        symlink_dir = tmp_path / "garth"
        symlink_dir.symlink_to(target_dir, target_is_directory=True)

        mock_garth = MagicMock()
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            [
                "--json",
                "--garmin-home", str(symlink_dir),
                "login",
                "--email", "cli@example.com",
                "--password", "clipass",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["error_code"] == "AUTH_FAILED"
        mock_garth.save.assert_not_called()


# ---------------------------------------------------------------------------
# garmin-cli login — failure paths
# ---------------------------------------------------------------------------

class TestLoginCommandFailure:

    def test_login_exits_one_on_auth_failure(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        result, _ = _run_login(
            ["login"],
            mocker,
            garth_side_effect=Exception("invalid credentials"),
            input="user@example.com\nwrongpassword\n",
            tmp_path=tmp_path,
        )
        assert result.exit_code == 1

    def test_login_failure_outputs_error_message(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.login.side_effect = Exception("invalid credentials")
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = str(tmp_path / "garth")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--garmin-home", garth_dir, "login"],
            input="user@example.com\nwrongpassword\n",
            catch_exceptions=False,
        )
        # Error message should be non-empty (check combined output)
        combined = result.output + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
        assert combined.strip() != ""

    def test_login_failure_json_mode_outputs_error_envelope(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.login.side_effect = Exception("invalid credentials")
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = str(tmp_path / "garth")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            [
                "--json", "--garmin-home", garth_dir, "login",
                "--email", "user@example.com", "--password", "wrongpassword",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["ok"] is False

    def test_login_failure_json_has_auth_failed_error_code(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.login.side_effect = Exception("invalid credentials")
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = str(tmp_path / "garth")
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            [
                "--json", "--garmin-home", garth_dir, "login",
                "--email", "user@example.com", "--password", "wrongpassword",
            ],
            catch_exceptions=False,
        )
        parsed = json.loads(result.output)
        assert parsed["error_code"] == "AUTH_FAILED"


# ---------------------------------------------------------------------------
# garmin-cli login status — session present
# ---------------------------------------------------------------------------

class TestLoginStatusLoggedIn:

    def test_status_exits_zero_when_session_valid(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--garmin-home", str(garth_dir), "login", "status"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0

    def test_status_calls_garth_resume(self, mocker: Any, tmp_path: Path) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)
        runner = CliRunner(mix_stderr=False)
        runner.invoke(
            cli,
            ["--garmin-home", str(garth_dir), "login", "status"],
            catch_exceptions=False,
        )
        mock_garth.resume.assert_called_once()

    def test_status_shows_logged_in_message(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--garmin-home", str(garth_dir), "login", "status"],
            catch_exceptions=False,
        )
        output = result.output.lower()
        assert "logged in" in output or "authenticated" in output or "active" in output

    def test_status_json_mode_ok_true_when_logged_in(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "--garmin-home", str(garth_dir), "login", "status"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True

    def test_status_json_mode_data_contains_authenticated_flag(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "--garmin-home", str(garth_dir), "login", "status"],
            catch_exceptions=False,
        )
        parsed = json.loads(result.output)
        # data should contain an authenticated field
        data = parsed.get("data", [])
        assert len(data) > 0
        assert "authenticated" in data[0]
        assert data[0]["authenticated"] is True

    def test_status_json_mode_marks_expired_session_unauthenticated(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(401)
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "--garmin-home", str(garth_dir), "login", "status"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["data"][0]["authenticated"] is False


# ---------------------------------------------------------------------------
# garmin-cli login status — no session
# ---------------------------------------------------------------------------

class TestLoginStatusNotLoggedIn:

    def test_status_exits_zero_when_no_session(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """login status should exit 0 even when not logged in (informational command)."""
        mock_garth = MagicMock()
        mock_garth.resume.side_effect = FileNotFoundError("no session")
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = tmp_path / "no_garth"
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--garmin-home", str(garth_dir), "login", "status"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0

    def test_status_shows_not_logged_in_message_when_no_session(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.resume.side_effect = FileNotFoundError("no session")
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = tmp_path / "no_garth"
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--garmin-home", str(garth_dir), "login", "status"],
            catch_exceptions=False,
        )
        output = result.output.lower()
        assert (
            "not logged in" in output
            or "no session" in output
            or "not authenticated" in output
        )

    def test_status_json_mode_data_authenticated_false_when_no_session(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.resume.side_effect = FileNotFoundError("no session")
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = tmp_path / "no_garth"
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "--garmin-home", str(garth_dir), "login", "status"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        data = parsed.get("data", [])
        assert len(data) > 0
        assert data[0]["authenticated"] is False

    def test_status_json_mode_shows_garmin_home(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.commands.login.garth", mock_garth)
        garth_dir = tmp_path / "garth"
        garth_dir.mkdir(mode=0o700)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli,
            ["--json", "--garmin-home", str(garth_dir), "login", "status"],
            catch_exceptions=False,
        )
        parsed = json.loads(result.output)
        data = parsed.get("data", [])
        assert len(data) > 0
        assert "garmin_home" in data[0]
