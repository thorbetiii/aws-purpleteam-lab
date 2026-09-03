"""Typed application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, PostgresDsn, field_validator, model_validator
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
    )

    name: str = "AWS Cloud Security Purple Team Lab"
    environment: Literal["local", "development", "test", "production"] = "local"
    version: str = "0.2.0"
    debug: bool = False
    database_url: PostgresDsn = Field(repr=False)

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
