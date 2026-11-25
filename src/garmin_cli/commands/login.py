"""Login commands for saving and removing Garmin Connect session tokens."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any

import click
from click.core import ParameterSource

from garmin_cli import backend as garth
from garmin_cli.auth import _persist_session, _secure_directory, resume_and_probe
from garmin_cli.backend import PendingMFA
from garmin_cli.commands import _options
from garmin_cli.commands._options import OutputGroup, output_options
from garmin_cli.exceptions import GarminCliError, login_error
from garmin_cli.output import render_output
from garmin_cli.token_store import tokenstore_path, validate_garmin_home

_COLUMNS_SESSION = ("authenticated", "garmin_home")


def _prompt_mfa_code() -> str:
    """Prompt the user for an MFA code when Garmin requires one."""
    return _options.prompt_line("MFA code").strip()


def _missing_credentials() -> GarminCliError:
    return GarminCliError(
        error=(
            "Garmin credentials are missing. Pass --email (or set GARMIN_EMAIL) "
            "and set GARMIN_PASSWORD or pipe the password to --password-stdin."
        ),
        error_code="AUTH_MISSING",
    )


@output_options
@click.group(cls=OutputGroup, invoke_without_command=True)
@click.option("--email", default=None, help="Garmin Connect email (default: GARMIN_EMAIL).")
@click.option(
    "--password",
    default=None,
    help=(
        "Deprecated: exposed in shell history and process listings. "
        "Use GARMIN_PASSWORD or --password-stdin."
    ),
)
@click.option(
    "--password-stdin",
    is_flag=True,
    help="Read the password from the first line of piped (non-terminal) stdin.",
)
@click.option(
    "--mfa-code",
    envvar="GARMIN_MFA_CODE",
    default=None,
    help=(
        "MFA code valid for the challenge this login starts, e.g. from an "
        "authenticator app (default: GARMIN_MFA_CODE). For emailed or SMS codes, "
        "run `garmin-cli login` interactively instead."
    ),
)
@click.pass_context
def login(
    ctx: click.Context,
    email: str | None,
    password: str | None,
    password_stdin: bool,
    mfa_code: str | None,
) -> None:
    """Login to Garmin Connect and save session tokens to the Garmin home directory."""
    if ctx.invoked_subcommand is not None:
        return

    config = ctx.obj["config"]
    garmin_home = os.path.expanduser(config.garth_home)
    output_format = config.output_format
    # Prompts would corrupt JSON/CSV output or hang a script waiting on stdin.
    interactive = output_format == "table" and _options.stdin_is_tty()

    if password_stdin:
        if password is not None:
            raise GarminCliError(
                error="Use either --password or --password-stdin, not both.",
                error_code="INVALID_INPUT",
            )
        if _options.stdin_is_tty():
            raise GarminCliError(
                error="--password-stdin needs the password piped in, not a terminal.",
                error_code="INVALID_INPUT",
            )
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise _missing_credentials()  # never fall back to GARMIN_PASSWORD here
    elif password is None:
        password = config.password
    if email is None:
        email = config.email

    if not email or not password:
        if not interactive:
            raise _missing_credentials()
        email = email or _options.prompt_line("Email").strip()
        password = password or _options.prompt_line("Password", hidden=True)

    code = (mfa_code or "").strip()
    if interactive and ctx.get_parameter_source("mfa_code") is ParameterSource.ENVIRONMENT:
        code = ""  # at a terminal, prompt for the code Garmin actually sends
    mfa_asked = False

    def _mfa_code() -> str:
        nonlocal mfa_asked
        mfa_asked = True
        return code or _prompt_mfa_code()

    login_options: dict[str, Any] = {"garth_home": garmin_home}
    if code or interactive:
        login_options["prompt_mfa"] = _mfa_code
    else:
        login_options["return_on_mfa"] = True

    try:
        # Pre-flight: reject symlinks and fix permissions on an existing directory
        # before we send credentials over the network.
        _secure_directory(garmin_home)
        client = garth.login(email, password, **login_options)
        if isinstance(client, PendingMFA):
            raise GarminCliError(
                error=(
                    "Garmin requires a one-time MFA code. Run `garmin-cli login` in a "
                    "terminal to enter an emailed or SMS code when prompted; "
                    "--mfa-code / GARMIN_MFA_CODE only works for a code valid for the "
                    "new challenge (authenticator app)."
                ),
                error_code="MFA_REQUIRED",
            )
        # Pass this module's garth so tests patching it here stay effective.
        _persist_session(garmin_home, client, garth)
    except GarminCliError:
        raise
    except Exception as exc:
        if mfa_asked:
            raise login_error(
                exc, "The MFA code was rejected. Run `garmin-cli login` again for a new code."
            ) from exc
        raise login_error(exc) from exc

    if output_format != "table":
        render_output(
            output_format, "login", [{"authenticated": True, "garmin_home": garmin_home}],
            _COLUMNS_SESSION,
        )
    else:
        click.echo(
            f"Login successful. Token store saved at: {tokenstore_path(garmin_home)}"
        )


@login.command(name="status")
@click.pass_context
def login_status(ctx: click.Context) -> None:
    """Check current login status."""
    config = ctx.obj["config"]
    garmin_home = os.path.expanduser(config.garth_home)
    output_format = config.output_format

    # Read-only: validates the home and refuses symlinks, never chmods.
    # Missing or rejected sessions are "not logged in"; throttles,
    # 5xx, network and filesystem errors raise (exit 1). Pass the module-level
    # garth so tests can patch it here without also patching auth.garth.
    authenticated = resume_and_probe(garmin_home, garth, read_only=True)

    record = {"authenticated": authenticated, "garmin_home": garmin_home}

    if output_format != "table":
        render_output(output_format, "login status", [record], _COLUMNS_SESSION)
        return

    if authenticated:
        click.echo(f"Logged in. Token store at: {tokenstore_path(garmin_home)}")
    else:
        click.echo(
            f"Not logged in. No token store found at: {tokenstore_path(garmin_home)}"
        )


def _delete_token_file(token_file: Path) -> bool:
    """Unlink a token file; False if absent. Refuses symlinks."""
    try:
        if stat.S_ISLNK(token_file.lstat().st_mode):
            raise GarminCliError(
                error=f"Refusing to delete symlinked token file {token_file}.",
                error_code="AUTH_FAILED",
            )
        token_file.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise GarminCliError(
            error=f"Could not delete {token_file}: {exc.strerror or exc}",
            error_code="AUTH_FAILED",
        ) from exc
    return True


@login.command(name="logout")
@click.pass_context
def logout(ctx: click.Context) -> None:
    """Delete the saved Garmin session token file."""
    config = ctx.obj["config"]
    home = validate_garmin_home(config.garth_home)
    token_file = tokenstore_path(str(home))
    logged_out = _delete_token_file(token_file)

    if config.output_format != "table":
        render_output(
            config.output_format,
            "login logout",
            [{"logged_out": logged_out}],
            ("logged_out",),
        )
    elif logged_out:
        click.echo(f"Logged out. Deleted: {token_file}")
    else:
        click.echo(f"Not logged in. No token store found at: {token_file}")
