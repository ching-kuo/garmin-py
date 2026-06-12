"""Login commands for storing Garmin Connect credentials."""
from __future__ import annotations

import os

import click

from garmin_cli import backend as garth
from garmin_cli.auth import _probe_session, _secure_directory
from garmin_cli.exceptions import GarminCliError, extract_status_code
from garmin_cli.output import echo_json, make_envelope
from garmin_cli.token_store import tokenstore_path


def _prompt_mfa_code() -> str:
    """Prompt the user for an MFA code when Garmin requires one."""
    return click.prompt("MFA code").strip()


@click.group(invoke_without_command=True)
@click.option("--email", default=None, help="Garmin Connect email.")
@click.option("--password", default=None, help="Garmin Connect password.")
@click.pass_context
def login(ctx: click.Context, email: str | None, password: str | None) -> None:
    """Login to Garmin Connect and save credentials to the Garmin home directory."""
    if ctx.invoked_subcommand is not None:
        return

    config = ctx.obj["config"]
    garmin_home = os.path.expanduser(config.garth_home)
    output_format = config.output_format

    if output_format == "json" and (email is None or password is None):
        raise GarminCliError(
            error="JSON login requires both --email and --password.",
            error_code="INVALID_INPUT",
        )

    if email is None:
        email = click.prompt("Email")
    if password is None:
        password = click.prompt("Password", hide_input=True)

    try:
        # Pre-flight: reject symlinks and fix permissions on an existing directory
        # before we send credentials over the network.
        _secure_directory(garmin_home)
        garth.login(
            email,
            password,
            garth_home=garmin_home,
            prompt_mfa=_prompt_mfa_code,
        )
        os.makedirs(garmin_home, mode=0o700, exist_ok=True)
        garth.save(garmin_home)
    except GarminCliError:
        raise
    except Exception as exc:
        if extract_status_code(exc) == 429:
            raise GarminCliError(
                error="Garmin login is temporarily rate limited. Try again shortly.",
                error_code="RATE_LIMITED",
            ) from exc
        raise GarminCliError(
            error="Authentication failed. Check your credentials.",
            error_code="AUTH_FAILED",
        ) from exc

    if output_format == "json":
        echo_json(make_envelope("login", [{"authenticated": True, "garmin_home": garmin_home}]))
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

    authenticated = False
    try:
        # Reject symlinks before attempting to read session tokens.
        _secure_directory(garmin_home)
        garth.resume(garmin_home)
        try:
            # Pass the module-level garth so tests can patch it via mocker
            # without needing to patch auth.garth as a separate target.
            _probe_session(garth)
            authenticated = True
        except Exception as exc:
            if extract_status_code(exc) not in (401, 403):
                raise GarminCliError(
                    error="Saved Garmin session could not be validated.",
                    error_code="AUTH_FAILED",
                ) from exc
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise GarminCliError(
            error=f"Cannot access session directory: {exc}",
            error_code="AUTH_FAILED",
        ) from exc
    except GarminCliError:
        raise
    except Exception:
        pass

    record = {"authenticated": authenticated, "garmin_home": garmin_home}

    if output_format == "json":
        echo_json(make_envelope("login status", [record]))
        return

    if authenticated:
        click.echo(f"Logged in. Token store at: {tokenstore_path(garmin_home)}")
    else:
        click.echo(
            f"Not logged in. No token store found at: {tokenstore_path(garmin_home)}"
        )
