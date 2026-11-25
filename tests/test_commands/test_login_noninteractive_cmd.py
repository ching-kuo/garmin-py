"""CLI tests for non-interactive login (env, stdin, MFA code) and logout."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import ANY, MagicMock

import pytest
from click.testing import CliRunner

from garmin_cli.backend import PendingMFA
from garmin_cli.cli import cli


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GARMIN_EMAIL", "GARMIN_PASSWORD", "GARMIN_MFA_CODE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def garth(mocker: Any) -> MagicMock:
    mock_garth = MagicMock()
    mock_garth.login.return_value = None
    mocker.patch("garmin_cli.commands.login.garth", mock_garth)
    return mock_garth


def _invoke(tmp_path: Path, args: list[str], *, input: str | None = None) -> Any:
    home = str(tmp_path / "garth")
    return CliRunner(mix_stderr=False).invoke(
        cli, ["--garmin-home", home, *args], input=input, catch_exceptions=False
    )


def test_password_from_env_when_option_absent(
    garth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARMIN_PASSWORD", "env-pass")

    result = _invoke(tmp_path, ["--json", "login", "--email", "a@example.com"])

    assert result.exit_code == 0, result.output
    garth.login.assert_called_once_with(
        "a@example.com", "env-pass", garth_home=str(tmp_path / "garth"), return_on_mfa=True
    )


def test_password_stdin_reads_one_line(garth: MagicMock, tmp_path: Path) -> None:
    result = _invoke(
        tmp_path,
        ["--json", "login", "--email", "a@example.com", "--password-stdin"],
        input="stdin-pass\nignored\n",
    )

    assert result.exit_code == 0, result.output
    assert garth.login.call_args.args == ("a@example.com", "stdin-pass")


def test_password_stdin_from_terminal_is_rejected(
    garth: MagicMock, tmp_path: Path, mocker: Any
) -> None:
    mocker.patch("garmin_cli.commands._options.stdin_is_tty", return_value=True)

    result = _invoke(tmp_path, ["--json", "login", "--email", "a@example.com", "--password-stdin"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "INVALID_INPUT"
    garth.login.assert_not_called()


@pytest.mark.parametrize("stdin", ["", "\n"])
def test_password_stdin_empty_is_auth_missing_without_env_fallback(
    garth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin: str
) -> None:
    monkeypatch.setenv("GARMIN_PASSWORD", "env-pass")

    result = _invoke(
        tmp_path,
        ["--json", "login", "--email", "a@example.com", "--password-stdin"],
        input=stdin,
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "AUTH_MISSING"
    garth.login.assert_not_called()


def test_password_and_password_stdin_are_exclusive(garth: MagicMock, tmp_path: Path) -> None:
    result = _invoke(
        tmp_path,
        ["--json", "login", "--email", "a@example.com", "--password", "x", "--password-stdin"],
        input="y\n",
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "INVALID_INPUT"
    garth.login.assert_not_called()


def test_non_tty_without_credentials_fails_auth_missing_without_prompting(
    garth: MagicMock, tmp_path: Path
) -> None:
    result = _invoke(tmp_path, ["login"], input="")

    assert result.exit_code == 1
    assert "AUTH_MISSING" not in result.stdout  # plain mode: message on stderr
    assert "Email" not in result.stderr  # never prompted
    assert "credentials" in result.stderr.lower()
    garth.login.assert_not_called()


def test_json_mfa_without_code_fails_mfa_required(garth: MagicMock, tmp_path: Path) -> None:
    garth.login.return_value = PendingMFA(client=MagicMock(), client_state={}, garth_home=None)

    result = _invoke(tmp_path, ["--json", "login", "--email", "a@example.com", "--password", "p"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "MFA_REQUIRED"
    assert "--mfa-code" in payload["error"]
    garth.save.assert_not_called()


@pytest.mark.parametrize("source", ["option", "env"])
def test_mfa_code_is_supplied_without_prompt(
    garth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    args = ["--json", "login", "--email", "a@example.com", "--password", "p"]
    if source == "option":
        args += ["--mfa-code", "123456"]
    else:
        monkeypatch.setenv("GARMIN_MFA_CODE", "123456")

    result = _invoke(tmp_path, args)

    assert result.exit_code == 0, result.output
    garth.login.assert_called_once_with(
        "a@example.com", "p", garth_home=str(tmp_path / "garth"), prompt_mfa=ANY
    )
    assert garth.login.call_args.kwargs["prompt_mfa"]() == "123456"
    garth.save.assert_called_once()


def test_whitespace_mfa_code_counts_as_absent(
    garth: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARMIN_MFA_CODE", "   ")

    result = _invoke(tmp_path, ["--json", "login", "--email", "a@example.com", "--password", "p"])

    assert result.exit_code == 0, result.output
    assert garth.login.call_args.kwargs == {
        "garth_home": str(tmp_path / "garth"),
        "return_on_mfa": True,
    }


def test_password_help_marks_option_deprecated() -> None:
    result = CliRunner().invoke(cli, ["login", "--help"])

    assert "Deprecated" in result.output
    assert "--password-stdin" in result.output
    assert "authenticator" in result.output
    assert "saves credentials" not in result.output


def test_logout_deletes_token_file(tmp_path: Path) -> None:
    home = tmp_path / "garth"
    home.mkdir(mode=0o700)
    (home / "garmin_tokens.json").write_text("{}")

    result = _invoke(tmp_path, ["--json", "login", "logout"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "login logout"
    assert payload["data"] == [{"logged_out": True}]
    assert not (home / "garmin_tokens.json").exists()


def test_logout_with_nothing_to_delete_exits_zero(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["--json", "login", "logout"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"] == [{"logged_out": False}]


def test_logout_default_home_leaves_legacy_garth_token_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("GARMIN_HOME", raising=False)
    for name in (".garminconnect", ".garth"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "garmin_tokens.json").write_text("{}")

    result = CliRunner(mix_stderr=False).invoke(cli, ["--json", "login", "logout"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"] == [{"logged_out": True}]
    assert (tmp_path / ".garth" / "garmin_tokens.json").exists()
    assert not (tmp_path / ".garminconnect" / "garmin_tokens.json").exists()


def test_logout_text_names_the_deleted_file(tmp_path: Path) -> None:
    home = tmp_path / "garth"
    home.mkdir(mode=0o700)
    (home / "garmin_tokens.json").write_text("{}")

    result = _invoke(tmp_path, ["login", "logout"])

    assert result.exit_code == 0
    assert str(home / "garmin_tokens.json") in result.stdout


@pytest.mark.parametrize("trailing_slash", ["", "/"])
def test_logout_refuses_symlinked_home_component(tmp_path: Path, trailing_slash: str) -> None:
    real = tmp_path / "real"
    (real / "garth").mkdir(parents=True)
    (real / "garth" / "garmin_tokens.json").write_text("{}")
    (tmp_path / "link").symlink_to(real)

    result = CliRunner(mix_stderr=False).invoke(
        cli,
        ["--json", "--garmin-home", f"{tmp_path / 'link' / 'garth'}{trailing_slash}", "login", "logout"],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "AUTH_FAILED"
    assert (real / "garth" / "garmin_tokens.json").exists()


def test_logout_unlink_failure_is_auth_failed(tmp_path: Path, mocker: Any) -> None:
    home = tmp_path / "garth"
    home.mkdir(mode=0o700)
    (home / "garmin_tokens.json").write_text("{}")
    mocker.patch.object(Path, "unlink", side_effect=PermissionError(13, "Permission denied"))

    result = _invoke(tmp_path, ["--json", "login", "logout"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "AUTH_FAILED"


def test_logout_refuses_symlinked_token_file(tmp_path: Path) -> None:
    home = tmp_path / "garth"
    home.mkdir(mode=0o700)
    target = tmp_path / "elsewhere.json"
    target.write_text("{}")
    (home / "garmin_tokens.json").symlink_to(target)

    result = _invoke(tmp_path, ["--json", "login", "logout"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "AUTH_FAILED"
    assert target.exists()
    assert (home / "garmin_tokens.json").is_symlink()
