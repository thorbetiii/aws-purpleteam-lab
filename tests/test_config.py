"""Tests for environment-based application configuration."""

import pytest
from pydantic import PostgresDsn, SecretStr, ValidationError

from app.core.config import Settings


VALID_DATABASE_URL = (
    "postgresql+psycopg://test_user:test_password@127.0.0.1:1/test_db"
)
VALID_JWT_SECRET = "test-only-jwt-signing-secret-never-use-in-a-real-environment"


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


def test_jwt_secret_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application settings fail clearly when the signing secret is absent."""
    monkeypatch.delenv("APP_JWT_SECRET", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(database_url=VALID_DATABASE_URL, _env_file=None)

    errors = exc_info.value.errors()
    assert any(
        error["loc"] == ("jwt_secret",) and error["type"] == "missing"
        for error in errors
    )


def test_jwt_configuration_is_typed_explicit_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JWT configuration is environment-driven without exposing its secret."""
    monkeypatch.setenv("APP_JWT_SECRET", VALID_JWT_SECRET)
    monkeypatch.setenv("APP_JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("APP_JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15")

    settings = Settings(database_url=VALID_DATABASE_URL, _env_file=None)

    assert isinstance(settings.jwt_secret, SecretStr)
    assert settings.jwt_secret.get_secret_value() == VALID_JWT_SECRET
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_access_token_expire_minutes == 15
    assert VALID_JWT_SECRET not in repr(settings)


def test_settings_reject_short_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HS256 configuration requires a nontrivial environment-provided secret."""
    short_secret = "distinctive-private-short"
    monkeypatch.setenv("APP_JWT_SECRET", short_secret)

    with pytest.raises(
        ValidationError,
        match="at least 32 characters",
    ) as exc_info:
        Settings(database_url=VALID_DATABASE_URL, _env_file=None)

    assert short_secret not in str(exc_info.value)


@pytest.mark.parametrize(
    ("variable_name", "invalid_value"),
    [
        ("APP_JWT_ALGORITHM", "none"),
        ("APP_JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "0"),
        ("APP_JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "61"),
    ],
)
def test_settings_reject_unsafe_jwt_configuration(
    monkeypatch: pytest.MonkeyPatch,
    variable_name: str,
    invalid_value: str,
) -> None:
    """The signer algorithm and short token-lifetime bounds are constrained."""
    monkeypatch.setenv(variable_name, invalid_value)

    with pytest.raises(ValidationError):
        Settings(database_url=VALID_DATABASE_URL, _env_file=None)


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
