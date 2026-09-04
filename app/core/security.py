"""Password hashing and minimal signed access-token utilities."""

from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import Settings


class AuthenticationTokenError(ValueError):
    """Raised when an access token cannot identify a valid user ID."""


MAX_POSTGRES_BIGINT = 9_223_372_036_854_775_807
_password_hasher = PasswordHash.recommended()
_dummy_password_hash = _password_hasher.hash(
    "phase3-dummy-password-used-only-to-balance-login-work"
)


def hash_password(plaintext_password: str) -> str:
    """Derive a salted Argon2 password hash suitable for database storage."""
    return _password_hasher.hash(plaintext_password)


def verify_password(plaintext_password: str, stored_hash: str) -> bool:
    """Verify a plaintext candidate without exposing malformed-hash details."""
    try:
        return _password_hasher.verify(plaintext_password, stored_hash)
    except UnknownHashError:
        return False


def verify_password_or_dummy(
    plaintext_password: str,
    stored_hash: str | None,
) -> bool:
    """Perform comparable Argon2 work even when no user hash was found."""
    candidate_hash = (
        _dummy_password_hash if stored_hash is None else stored_hash
    )
    verified = verify_password(plaintext_password, candidate_hash)
    return stored_hash is not None and verified


def create_access_token(
    *,
    user_id: int,
    settings: Settings,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT containing only a subject and expiration."""
    if not 1 <= user_id <= MAX_POSTGRES_BIGINT:
        raise ValueError("user_id must fit a positive PostgreSQL BIGINT")

    lifetime = expires_delta
    if lifetime is None:
        lifetime = timedelta(
            minutes=settings.jwt_access_token_expire_minutes,
        )

    expires_at = datetime.now(timezone.utc) + lifetime
    return jwt.encode(
        {"sub": str(user_id), "exp": expires_at},
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str, *, settings: Settings) -> int:
    """Validate a JWT and return its strictly formatted positive user ID."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
    except (InvalidTokenError, TypeError, ValueError, OverflowError) as exc:
        raise AuthenticationTokenError("Invalid access token") from exc

    subject = payload.get("sub")
    if (
        not isinstance(subject, str)
        or not subject.isascii()
        or not subject.isdecimal()
        or len(subject) > 19
    ):
        raise AuthenticationTokenError("Invalid access token subject")

    user_id = int(subject)
    if (
        user_id <= 0
        or user_id > MAX_POSTGRES_BIGINT
        or str(user_id) != subject
    ):
        raise AuthenticationTokenError("Invalid access token subject")
    return user_id
