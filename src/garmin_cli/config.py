"""Configuration dataclass and environment variable loading."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from garmin_cli.token_store import DEFAULT_GARMIN_HOME, expand_garmin_home

GARTH_HOME_HINT = "GARTH_HOME is no longer read; set GARMIN_HOME."


def garth_home_ignored(garmin_home: str) -> bool:
    """True when the removed GARTH_HOME is set but the default Garmin home is in use."""
    return bool(os.environ.get("GARTH_HOME")) and expand_garmin_home(garmin_home) == expand_garmin_home(
        DEFAULT_GARMIN_HOME
    )

# Click ctx.obj key: the command path, set once a leaf command's options are
# parsed, so error reporting can trust the parsed output format.
PARSED_COMMAND = "parsed_command"


def command_path(ctx: Any) -> str:
    """Command names from a click context chain, without the program name."""
    names: list[str] = []
    while ctx is not None and ctx.parent is not None:
        names.append(ctx.info_name or "")
        ctx = ctx.parent
    return " ".join(reversed(names))


@dataclass(frozen=True)
class CliConfig:
    """Immutable CLI configuration."""

    email: str | None = None
    password: str | None = field(default=None, repr=False)
    garth_home: str = DEFAULT_GARMIN_HOME
    output_format: str = "table"


def load_config() -> CliConfig:
    """Load configuration from environment variables."""
    email_raw = os.environ.get("GARMIN_EMAIL")
    password_raw = os.environ.get("GARMIN_PASSWORD")
    garth_home = os.environ.get("GARMIN_HOME") or DEFAULT_GARMIN_HOME

    return CliConfig(
        email=email_raw if email_raw != "" else None,
        password=password_raw if password_raw != "" else None,
        garth_home=garth_home,
    )
