"""Typed application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import (
    Field,
    PostgresDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from APP_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    name: str = "AWS Cloud Security Purple Team Lab"
    environment: Literal["local", "development", "test", "production"] = "local"
    version: str = "0.3.0"
    debug: bool = False
    database_url: PostgresDsn = Field(repr=False)
    jwt_secret: SecretStr = Field(repr=False)
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=15, ge=1, le=60)

    @field_validator("database_url")
    @classmethod
    def require_psycopg_driver(
        cls,
        database_url: PostgresDsn,
    ) -> PostgresDsn:
        """Keep the configured SQLAlchemy URL aligned with the installed driver."""
        if database_url.scheme != "postgresql+psycopg":
            raise ValueError(
                "APP_DATABASE_URL must use the postgresql+psycopg scheme"
            )
        return database_url

    @field_validator("jwt_secret")
    @classmethod
    def require_sufficient_jwt_secret_length(
        cls,
        jwt_secret: SecretStr,
    ) -> SecretStr:
        """Require enough secret material for the configured HS256 signer."""
        if len(jwt_secret.get_secret_value()) < 32:
            raise ValueError("APP_JWT_SECRET must contain at least 32 characters")
        return jwt_secret

    @model_validator(mode="after")
    def reject_debug_in_production(self) -> Self:
        """Prevent production from starting with debug error handling enabled."""
        if self.environment == "production" and self.debug:
            raise ValueError(
                "APP_DEBUG must be false when APP_ENVIRONMENT is production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Load and cache settings once for the lifetime of the process."""
    return Settings()
