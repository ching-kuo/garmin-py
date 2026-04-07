"""Tests for garmin_cli.config — CliConfig dataclass and load_config()."""
from __future__ import annotations

import os
from typing import Any

import pytest

from garmin_cli.config import CliConfig, load_config


class TestCliConfig:
    """Unit tests for the CliConfig frozen dataclass."""

    def test_default_values(self) -> None:
        config = CliConfig()
        assert config.email is None
        assert config.password is None
        assert config.garth_home == "~/.garth"
        assert config.output_format == "table"

    def test_custom_values(self) -> None:
        config = CliConfig(
            email="user@example.com",
            password="secret123",
            garth_home="/custom/garth",
            output_format="json",
        )
        assert config.email == "user@example.com"
        assert config.password == "secret123"
        assert config.garth_home == "/custom/garth"
        assert config.output_format == "json"

    def test_is_frozen(self) -> None:
        config = CliConfig(email="a@b.com")
        with pytest.raises((AttributeError, TypeError)):
            config.email = "other@b.com"  # type: ignore[misc]




class TestLoadConfig:
    """Unit tests for load_config() reading from environment variables."""

    def test_load_config_reads_email_from_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("GARMIN_EMAIL", "env@test.com")
        monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("GARTH_HOME", raising=False)
        config = load_config()
        assert config.email == "env@test.com"

    def test_load_config_reads_password_from_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("GARMIN_PASSWORD", "envpass")
        monkeypatch.delenv("GARMIN_EMAIL", raising=False)
        monkeypatch.delenv("GARTH_HOME", raising=False)
        config = load_config()
        assert config.password == "envpass"

    def test_load_config_reads_garth_home_from_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("GARTH_HOME", "/env/garth")
        monkeypatch.delenv("GARMIN_EMAIL", raising=False)
        monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
        config = load_config()
        assert config.garth_home == "/env/garth"

    def test_load_config_defaults_when_no_env(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("GARMIN_EMAIL", raising=False)
        monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("GARTH_HOME", raising=False)
        config = load_config()
        assert config.email is None
        assert config.password is None
        assert config.garth_home == "~/.garth"

    def test_load_config_all_env_vars(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("GARMIN_EMAIL", "full@test.com")
        monkeypatch.setenv("GARMIN_PASSWORD", "fullpass")
        monkeypatch.setenv("GARTH_HOME", "/full/garth")
        config = load_config()
        assert config.email == "full@test.com"
        assert config.password == "fullpass"
        assert config.garth_home == "/full/garth"

    def test_load_config_empty_string_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("GARMIN_EMAIL", "")
        monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
        monkeypatch.delenv("GARTH_HOME", raising=False)
        config = load_config()
        # Empty string env var should be treated as None or empty — implementation decides
        assert config.email == "" or config.email is None
