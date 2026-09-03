"""Tests for environment-based application configuration."""

import pytest
from pydantic import PostgresDsn, ValidationError

from app.core.config import Settings


VALID_DATABASE_URL = (
    "postgresql+psycopg://test_user:test_password@127.0.0.1:1/test_db"
)


@pytest.mark.parametrize(
    "hostname",
    [
        "localhost",
        "purple-team-db.cluster-example.us-east-1.rds.amazonaws.com",
    ],
)
def test_settings_accept_postgresql_psycopg_database_urls(
    monkeypatch: pytest.MonkeyPatch,
    hostname: str,
) -> None:
    """The same setting supports local PostgreSQL and a future RDS hostname."""
    monkeypatch.setenv(
        "APP_DATABASE_URL",
        f"postgresql+psycopg://app_user:dev_password@{hostname}:5432/app_db",
    )

    settings = Settings(_env_file=None)

    assert isinstance(settings.database_url, PostgresDsn)
    assert settings.database_url.scheme == "postgresql+psycopg"
    assert settings.database_url.path == "/app_db"
    assert settings.database_url.hosts()[0]["host"] == hostname
    assert "database_url" not in repr(settings)
    assert "dev_password" not in repr(settings)


def test_database_url_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application settings fail clearly when the database URL is absent."""
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert exc_info.value.errors()[0]["loc"] == ("database_url",)
    assert exc_info.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///misleading-test.db",
        "postgresql://app_user:dev_password@localhost:5432/app_db",
    ],
)
def test_settings_reject_unsupported_database_urls(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    """The setting must select PostgreSQL through the installed psycopg driver."""
    monkeypatch.setenv("APP_DATABASE_URL", database_url)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_read_app_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """APP_* variables override defaults and booleans are parsed."""
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv("APP_DEBUG", "true")

    settings = Settings(database_url=VALID_DATABASE_URL, _env_file=None)

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
        Settings(database_url=VALID_DATABASE_URL, _env_file=None)
