"""API and schema tests for registration, login, and current-user lookup."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import os
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
import pytest
from sqlalchemy import Engine, create_engine, delete, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.security import create_access_token, decode_access_token, hash_password
from app.db.session import get_db_session
from app.main import create_app
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserPublic


TEST_DATABASE_URL = (
    "postgresql+psycopg://test_user:test_password@127.0.0.1:1/test_db"
)
TEST_JWT_SECRET = "test-only-jwt-signing-secret-never-use-in-a-real-environment"
VALID_PASSWORD = "correct horse battery staple"


class _UsernameUniqueViolation(Exception):
    """Minimal PostgreSQL unique-violation metadata used by the route."""

    sqlstate = "23505"
    diag = SimpleNamespace(constraint_name="uq_users_username")


def _settings(*, database_url: str = TEST_DATABASE_URL) -> Settings:
    """Build deterministic request settings without reading a local .env file."""
    return Settings(
        environment="test",
        database_url=database_url,
        jwt_secret=TEST_JWT_SECRET,
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=15,
        _env_file=None,
    )


def _user(
    *,
    user_id: int = 1001,
    username: str = "alice",
    password_hash: str,
) -> User:
    """Return a complete ORM user suitable for response-model serialization."""
    return User(
        id=user_id,
        username=username,
        password_hash=password_hash,
        role="user",
        created_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
    )


def _session_with_lookup(user: User | None) -> MagicMock:
    """Support the common SQLAlchemy lookup forms without using SQLite."""
    session = MagicMock(spec=Session)
    session.scalar.return_value = user
    session.get.return_value = user
    session.execute.return_value.scalar_one_or_none.return_value = user
    return session


def _application_with_session(
    session: Session | MagicMock,
    *,
    settings: Settings | None = None,
) -> FastAPI:
    """Create an isolated application whose DB dependency yields one test session."""
    application = create_app()
    test_settings = settings or _settings()

    def override_session() -> Generator[Session | MagicMock, None, None]:
        yield session

    application.dependency_overrides[get_settings] = lambda: test_settings
    application.dependency_overrides[get_db_session] = override_session
    return application


async def _request(
    application: FastAPI,
    method: str,
    path: str,
    **kwargs: object,
):
    """Issue one request against an in-process FastAPI application."""
    transport = ASGITransport(app=application)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.request(method, path, **kwargs)


def test_credential_schemas_normalize_only_the_username() -> None:
    """Both flows trim/lower usernames while preserving password bytes as entered."""
    password = "  correct horse battery staple  "

    registration = RegisterRequest(username="  Alice  ", password=password)
    login = LoginRequest(username="\tALICE\n", password=password)

    assert registration.username == "alice"
    assert login.username == "alice"
    assert isinstance(registration.password, SecretStr)
    assert isinstance(login.password, SecretStr)
    assert registration.password.get_secret_value() == password
    assert login.password.get_secret_value() == password


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("ab", VALID_PASSWORD),
        ("a" * 65, VALID_PASSWORD),
        ("alice", "x" * 11),
        ("alice", "x" * 129),
    ],
)
def test_registration_enforces_username_and_password_length_policy(
    username: str,
    password: str,
) -> None:
    """Normalized usernames are 3-64 chars and passwords are 12-128 chars."""
    with pytest.raises(ValidationError):
        RegisterRequest(username=username, password=password)


def test_registration_schema_rejects_role_selection() -> None:
    """There is no client-controlled role field, including an ignored extra one."""
    with pytest.raises(ValidationError):
        RegisterRequest.model_validate(
            {
                "username": "alice",
                "password": VALID_PASSWORD,
                "role": "admin",
            }
        )


@pytest.mark.anyio
async def test_registration_creates_normalized_user_with_user_role() -> None:
    """Successful self-registration hashes the password and returns safe fields."""
    session = _session_with_lookup(None)
    added_users: list[User] = []

    def record_user(user: User) -> None:
        added_users.append(user)

    def populate_database_values(user: User) -> None:
        user.id = 1001
        user.created_at = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

    session.add.side_effect = record_user
    session.refresh.side_effect = populate_database_values
    application = _application_with_session(session)

    response = await _request(
        application,
        "POST",
        "/auth/register",
        json={"username": "  Alice  ", "password": VALID_PASSWORD},
    )

    assert response.status_code == 201
    public_user = UserPublic.model_validate(response.json())
    assert public_user.id == 1001
    assert public_user.username == "alice"
    assert public_user.role == "user"
    assert added_users[0].username == "alice"
    assert added_users[0].role == "user"
    assert added_users[0].password_hash != VALID_PASSWORD
    assert added_users[0].password_hash.startswith("$argon2")
    assert "password_hash" not in response.text
    assert VALID_PASSWORD not in response.text
    session.commit.assert_called_once_with()


@pytest.mark.anyio
async def test_registration_rejects_admin_role_before_database_access() -> None:
    """Submitting an admin role fails validation and creates no user."""
    session = _session_with_lookup(None)
    application = _application_with_session(session)

    response = await _request(
        application,
        "POST",
        "/auth/register",
        json={
            "username": "alice",
            "password": VALID_PASSWORD,
            "role": "admin",
        },
    )

    assert response.status_code == 422
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.anyio
async def test_invalid_password_is_not_reflected_in_validation_response() -> None:
    """Request validation never returns a submitted plaintext password."""
    invalid_password = "leak-12345"
    session = _session_with_lookup(None)
    application = _application_with_session(session)

    response = await _request(
        application,
        "POST",
        "/auth/register",
        json={"username": "alice", "password": invalid_password},
    )

    assert response.status_code == 422
    assert invalid_password not in response.text
    assert response.json()["detail"][0]["input"] == "[redacted]"
    session.add.assert_not_called()


@pytest.mark.anyio
async def test_duplicate_username_returns_conflict_and_rolls_back() -> None:
    """The commit-time unique violation is converted to a safe duplicate response."""
    session = _session_with_lookup(None)
    duplicate = _UsernameUniqueViolation(
        'duplicate key value violates unique constraint "uq_users_username"'
    )
    session.commit.side_effect = IntegrityError(
        "INSERT INTO users ...",
        {"username": "alice"},
        duplicate,
    )
    application = _application_with_session(session)

    response = await _request(
        application,
        "POST",
        "/auth/register",
        json={"username": "Alice", "password": VALID_PASSWORD},
    )

    assert response.status_code == 409
    assert "username" in response.json()["detail"].lower()
    assert "constraint" not in response.text.lower()
    assert "duplicate key" not in response.text.lower()
    session.rollback.assert_called_once_with()


@pytest.mark.anyio
async def test_successful_login_returns_bearer_access_token() -> None:
    """Correct credentials produce a signed token for the database user ID."""
    settings = _settings()
    user = _user(password_hash=hash_password(VALID_PASSWORD))
    session = _session_with_lookup(user)
    application = _application_with_session(session, settings=settings)

    response = await _request(
        application,
        "POST",
        "/auth/login",
        json={"username": " ALICE ", "password": VALID_PASSWORD},
    )

    assert response.status_code == 200
    token_response = TokenResponse.model_validate(response.json())
    assert token_response.token_type == "bearer"
    assert token_response.expires_in == 15 * 60
    assert decode_access_token(
        token_response.access_token,
        settings=settings,
    ) == user.id
    assert "password_hash" not in response.text
    assert VALID_PASSWORD not in response.text


@pytest.mark.anyio
async def test_incorrect_logins_use_one_generic_authentication_failure() -> None:
    """Unknown usernames and wrong passwords are indistinguishable to clients."""
    user = _user(password_hash=hash_password(VALID_PASSWORD))
    unknown_application = _application_with_session(_session_with_lookup(None))
    wrong_password_application = _application_with_session(
        _session_with_lookup(user)
    )

    unknown_response = await _request(
        unknown_application,
        "POST",
        "/auth/login",
        json={"username": "unknown", "password": VALID_PASSWORD},
    )
    wrong_password_response = await _request(
        wrong_password_application,
        "POST",
        "/auth/login",
        json={"username": "alice", "password": "this password is incorrect"},
    )

    assert unknown_response.status_code == 401
    assert wrong_password_response.status_code == 401
    assert unknown_response.json() == wrong_password_response.json()
    failure_text = str(unknown_response.json()).lower()
    assert "unknown" not in failure_text
    assert VALID_PASSWORD not in failure_text
    assert "hash" not in failure_text


@pytest.mark.anyio
async def test_auth_me_rejects_missing_and_malformed_tokens() -> None:
    """The protected endpoint never accepts absent or malformed bearer tokens."""
    application = _application_with_session(_session_with_lookup(None))

    missing_response = await _request(application, "GET", "/auth/me")
    malformed_response = await _request(
        application,
        "GET",
        "/auth/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )

    assert missing_response.status_code == 401
    assert malformed_response.status_code == 401
    assert missing_response.headers["www-authenticate"].lower() == "bearer"
    assert malformed_response.headers["www-authenticate"].lower() == "bearer"


@pytest.mark.anyio
async def test_auth_me_rejects_expired_token() -> None:
    """An otherwise correctly signed token is unusable after expiration."""
    settings = _settings()
    expired_token = create_access_token(
        user_id=1001,
        settings=settings,
        expires_delta=timedelta(seconds=-1),
    )
    application = _application_with_session(
        _session_with_lookup(None),
        settings=settings,
    )

    response = await _request(
        application,
        "GET",
        "/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_auth_me_rejects_token_for_unknown_user() -> None:
    """A valid token cannot authenticate a user no longer present in PostgreSQL."""
    settings = _settings()
    token = create_access_token(user_id=1001, settings=settings)
    application = _application_with_session(
        _session_with_lookup(None),
        settings=settings,
    )

    response = await _request(
        application,
        "GET",
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_auth_me_returns_the_token_subject_user_without_password_hash() -> None:
    """A valid bearer token loads and safely serializes the matching DB user."""
    settings = _settings()
    user = _user(password_hash=hash_password(VALID_PASSWORD))
    token = create_access_token(user_id=user.id, settings=settings)
    session = _session_with_lookup(user)
    application = _application_with_session(session, settings=settings)

    response = await _request(
        application,
        "GET",
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    public_user = UserPublic.model_validate(response.json())
    assert public_user.id == user.id
    assert public_user.username == user.username
    assert public_user.role == user.role
    assert "password_hash" not in response.text
    assert user.password_hash not in response.text


@dataclass
class _PostgresTestDatabase:
    """Explicitly configured PostgreSQL session factory and cleanup allowlist."""

    engine: Engine
    session_factory: sessionmaker[Session]
    usernames_to_delete: set[str] = field(default_factory=set)

    def dependency(self) -> Generator[Session, None, None]:
        with self.session_factory() as session:
            yield session


@pytest.fixture
def postgres_auth_database() -> Generator[_PostgresTestDatabase, None, None]:
    """Use only an opt-in migrated PostgreSQL database and remove exact test rows."""
    database_url = os.environ.get("APP_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("set APP_TEST_DATABASE_URL to run PostgreSQL auth integration")

    parsed_url = make_url(database_url)
    if (
        parsed_url.get_backend_name() != "postgresql"
        or parsed_url.get_driver_name() != "psycopg"
    ):
        pytest.fail(
            "APP_TEST_DATABASE_URL must use PostgreSQL through postgresql+psycopg"
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    if not inspect(engine).has_table("users"):
        engine.dispose()
        pytest.fail(
            "APP_TEST_DATABASE_URL has no users table; run Alembic migrations first"
        )

    database = _PostgresTestDatabase(
        engine=engine,
        session_factory=sessionmaker(
            bind=engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        ),
    )

    try:
        yield database
    finally:
        if database.usernames_to_delete:
            with database.session_factory.begin() as cleanup_session:
                cleanup_session.execute(
                    delete(User).where(
                        User.username.in_(database.usernames_to_delete)
                    )
                )
        engine.dispose()


@pytest.mark.anyio
async def test_authentication_flow_against_postgresql(
    postgres_auth_database: _PostgresTestDatabase,
) -> None:
    """PostgreSQL enforces normalized uniqueness across the complete auth flow."""
    normalized_username = f"phase3_{uuid4().hex}"
    submitted_username = f"  {normalized_username.upper()}  "
    admin_username = f"{normalized_username}_admin"
    postgres_auth_database.usernames_to_delete.update(
        {
            normalized_username,
            normalized_username.upper(),
            submitted_username,
            admin_username,
        }
    )
    settings = _settings(database_url=str(postgres_auth_database.engine.url))
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_db_session] = (
        postgres_auth_database.dependency
    )

    registration = await _request(
        application,
        "POST",
        "/auth/register",
        json={
            "username": submitted_username,
            "password": VALID_PASSWORD,
        },
    )
    assert registration.status_code == 201
    assert registration.json()["username"] == normalized_username
    assert registration.json()["role"] == "user"
    assert "password_hash" not in registration.text

    with postgres_auth_database.session_factory() as inspection_session:
        stored_user = inspection_session.scalar(
            select(User).where(User.username == normalized_username)
        )
        assert stored_user is not None
        assert stored_user.password_hash != VALID_PASSWORD
        assert stored_user.password_hash.startswith("$argon2")

    duplicate = await _request(
        application,
        "POST",
        "/auth/register",
        json={"username": normalized_username, "password": VALID_PASSWORD},
    )
    assert duplicate.status_code == 409

    role_escalation = await _request(
        application,
        "POST",
        "/auth/register",
        json={
            "username": admin_username,
            "password": VALID_PASSWORD,
            "role": "admin",
        },
    )
    assert role_escalation.status_code == 422

    bad_login = await _request(
        application,
        "POST",
        "/auth/login",
        json={
            "username": normalized_username,
            "password": "this password is incorrect",
        },
    )
    assert bad_login.status_code == 401

    login = await _request(
        application,
        "POST",
        "/auth/login",
        json={"username": normalized_username, "password": VALID_PASSWORD},
    )
    assert login.status_code == 200
    token = TokenResponse.model_validate(login.json()).access_token

    current_user = await _request(
        application,
        "GET",
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert current_user.status_code == 200
    assert current_user.json()["username"] == normalized_username
    assert current_user.json()["role"] == "user"
    assert "password_hash" not in current_user.text
