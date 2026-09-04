"""Validated authentication requests and safe public responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$"


class CredentialsRequest(BaseModel):
    """Shared username and password input accepted by authentication routes."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=USERNAME_PATTERN,
        examples=["alice"],
    )
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, username: object) -> object:
        """Make application-managed usernames predictable and case-consistent."""
        if isinstance(username, str):
            return username.strip().lower()
        return username

    @field_validator("password")
    @classmethod
    def reject_whitespace_only_password(cls, password: SecretStr) -> SecretStr:
        """Keep whitespace meaningful without accepting an all-whitespace secret."""
        if not password.get_secret_value().strip():
            raise ValueError("Password cannot contain only whitespace")
        return password


class RegisterRequest(CredentialsRequest):
    """New-user credentials; role is intentionally not client-selectable."""


class LoginRequest(CredentialsRequest):
    """Credentials used to obtain a short-lived access token."""


class UserPublic(BaseModel):
    """Safe user fields that may leave the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Literal["user", "admin"]
    created_at: datetime


class TokenResponse(BaseModel):
    """Bearer access token returned after successful authentication."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0, description="Access-token lifetime in seconds")
