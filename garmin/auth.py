"""Garmin Connect authentication via the maintained backend."""

from __future__ import annotations

import logging
import sys
from typing import Protocol

from garmin_cli import backend as garth
logger = logging.getLogger(__name__)


class GarminConfig(Protocol):
    """Minimal config contract required for Garmin authentication."""

    garth_home: str
    email: str | None
    password: str | None


def login(config: GarminConfig) -> None:
    """Authenticate with Garmin Connect.

    Tries to resume an existing session from *garth_home*.  If that fails,
    logs in with the email / password from *config* (sourced from env vars)
    and persists the new session.
    """
    garth_home = config.garth_home

    try:
        garth.resume(garth_home)
        logger.info("Resumed Garmin session from %s", garth_home)
        return
    except Exception:
        pass  # session expired or missing — fall through to login

    if not config.email or not config.password:
        logger.error(
            "No saved session and GARMIN_EMAIL / GARMIN_PASSWORD are not set."
        )
        sys.exit(1)

    try:
        garth.login(config.email, config.password, garth_home=garth_home)
        garth.save(garth_home)
        logger.info("Logged in and saved session to %s", garth_home)
    except Exception as exc:
        logger.error("Garmin login failed: %s", exc)
        sys.exit(1)
