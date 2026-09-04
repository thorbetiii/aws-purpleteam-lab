"""Focused tests for Argon2 password handling and JWT access tokens."""

from datetime import timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    AuthenticationTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    verify_password_or_dummy,
)


TEST_DATABASE_URL = (
    "postgresql+psycopg://test_user:test_password@127.0.0.1:1/test_db"
)
TEST_JWT_SECRET = "test-only-jwt-signing-secret-never-use-in-a-real-environment"


def _settings(*, jwt_secret: str = TEST_JWT_SECRET) -> Settings:
    """Build isolated settings without reading a developer's local .env file."""
    return Settings(
        database_url=TEST_DATABASE_URL,
        jwt_secret=jwt_secret,
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=15,
        _env_file=None,
    )


def test_password_hash_is_argon2_and_never_plaintext() -> None:
    """Password storage uses an encoded Argon2 hash rather than plaintext."""
    plaintext = "correct horse battery staple"

    password_hash = hash_password(plaintext)

    assert password_hash != plaintext
    assert password_hash.startswith("$argon2")


def test_valid_password_verifies() -> None:
    """The original plaintext verifies against its stored Argon2 hash."""
    plaintext = "correct horse battery staple"
    password_hash = hash_password(plaintext)

    assert verify_password(plaintext, password_hash) is True


def test_invalid_password_does_not_verify() -> None:
    """A different plaintext cannot authenticate against the stored hash."""
    password_hash = hash_password("correct horse battery staple")

    assert verify_password("incorrect horse battery staple", password_hash) is False


def test_empty_stored_hash_cannot_fall_back_to_dummy_authentication() -> None:
    """A corrupt, empty database hash never authenticates via the dummy hash."""
    assert (
        verify_password_or_dummy(
            "phase3-dummy-password-used-only-to-balance-login-work",
            "",
        )
        is False
    )


def test_access_token_round_trip_uses_database_user_id_subject() -> None:
    """A signed, unexpired token resolves to its immutable database user ID."""
    settings = _settings()

    token = create_access_token(user_id=42, settings=settings)
    payload = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )

    assert set(payload) == {"sub", "exp"}
    assert payload["sub"] == "42"
    assert decode_access_token(token, settings=settings) == 42


def test_expired_access_token_is_rejected() -> None:
    """Standard JWT expiration is enforced during authentication."""
    settings = _settings()
    token = create_access_token(
        user_id=42,
        settings=settings,
        expires_delta=timedelta(seconds=-1),
    )

    with pytest.raises(AuthenticationTokenError):
        decode_access_token(token, settings=settings)


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        jwt.encode(
            {"sub": "42"},
            TEST_JWT_SECRET,
            algorithm="HS256",
        ),
        jwt.encode(
            {"sub": "not-an-integer", "exp": 4_102_444_800},
            TEST_JWT_SECRET,
            algorithm="HS256",
        ),
        jwt.encode(
            {"sub": "42", "exp": float("inf")},
            TEST_JWT_SECRET,
            algorithm="HS256",
        ),
        jwt.encode(
            {"sub": "42", "exp": {}},
            TEST_JWT_SECRET,
            algorithm="HS256",
        ),
        jwt.encode(
            {"sub": "9" * 5_000, "exp": 4_102_444_800},
            TEST_JWT_SECRET,
            algorithm="HS256",
        ),
        jwt.encode(
            {"sub": "9223372036854775808", "exp": 4_102_444_800},
            TEST_JWT_SECRET,
            algorithm="HS256",
        ),
    ],
)
def test_malformed_or_incomplete_access_token_is_rejected(token: str) -> None:
    """Malformed tokens and tokens without valid required claims are unusable."""
    with pytest.raises(AuthenticationTokenError):
        decode_access_token(token, settings=_settings())


def test_token_signed_with_another_secret_is_rejected() -> None:
    """A valid-looking token cannot be accepted under a different signing key."""
    token = create_access_token(user_id=42, settings=_settings())

    with pytest.raises(AuthenticationTokenError):
        decode_access_token(
            token,
            settings=_settings(
                jwt_secret="another-test-only-signing-secret-never-use-for-real"
            ),
        )
