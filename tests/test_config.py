"""Tests for environment-based application configuration."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_read_app_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """APP_* variables override defaults and booleans are parsed."""
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv("APP_DEBUG", "true")

    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.debug is True


def test_settings_reject_debug_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production cannot start with debug error handling enabled."""
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("APP_DEBUG", "true")

    with pytest.raises(
        ValidationError,
        match="APP_DEBUG must be false when APP_ENVIRONMENT is production",
    ):
        Settings(_env_file=None)
