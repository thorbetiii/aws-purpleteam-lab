"""Unit tests for lazy SQLAlchemy engine and session lifecycle management."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from pydantic import PostgresDsn
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import app.db.session as session_module


@pytest.fixture(autouse=True)
def clear_database_singletons() -> Iterator[None]:
    """Keep process-wide engine and factory caches isolated between tests."""
    get_engine = session_module.get_engine
    get_session_factory = session_module.get_session_factory
    get_session_factory.cache_clear()
    get_engine.cache_clear()

    yield

    get_session_factory.cache_clear()
    get_engine.cache_clear()


def test_get_engine_uses_psycopg_pre_ping_and_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Engine construction preserves the PostgreSQL driver and pool check."""
    database_url = PostgresDsn(
        "postgresql+psycopg://app_user:dev_password@localhost:5432/app_db"
    )
    engine = MagicMock(spec=Engine)
    create_engine = Mock(return_value=engine)
    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: SimpleNamespace(database_url=database_url),
    )
    monkeypatch.setattr(session_module, "create_engine", create_engine)

    first = session_module.get_engine()
    second = session_module.get_engine()

    assert first is engine
    assert second is engine
    create_engine.assert_called_once_with(str(database_url), pool_pre_ping=True)
    sqlalchemy_url = make_url(create_engine.call_args.args[0])
    assert sqlalchemy_url.get_backend_name() == "postgresql"
    assert sqlalchemy_url.get_driver_name() == "psycopg"


def test_session_factory_has_request_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cached factory binds sessions with explicit SQLAlchemy 2.x behavior."""
    database_url = PostgresDsn(
        "postgresql+psycopg://app_user:dev_password@localhost:5432/app_db"
    )
    engine = MagicMock(spec=Engine)
    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: SimpleNamespace(database_url=database_url),
    )
    monkeypatch.setattr(session_module, "create_engine", Mock(return_value=engine))

    first = session_module.get_session_factory()
    second = session_module.get_session_factory()

    assert first is second
    # sessionmaker creates an internal Session subclass, so behavior is better
    # represented by subclass compatibility than by class-object identity.
    assert issubclass(first.class_, Session)
    assert first.kw["bind"] is engine
    assert first.kw["autoflush"] is False
    assert first.kw["expire_on_commit"] is False


def test_database_dependency_closes_the_request_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completing a dependency scope closes its SQLAlchemy session."""

    class RecordingSession:
        def __init__(self) -> None:
            self.closed = False

        def __enter__(self) -> "RecordingSession":
            return self

        def __exit__(self, *_args: object) -> None:
            self.closed = True

    session = RecordingSession()
    factory = Mock(return_value=session)
    monkeypatch.setattr(session_module, "get_session_factory", lambda: factory)

    dependency = session_module.get_db_session()
    yielded_session = next(dependency)

    assert yielded_session is session
    assert session.closed is False

    with pytest.raises(StopIteration):
        next(dependency)

    assert session.closed is True
    factory.assert_called_once_with()


def test_dispose_engine_releases_only_an_initialized_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown disposal releases cached pools and clears both singletons."""
    database_url = PostgresDsn(
        "postgresql+psycopg://app_user:dev_password@localhost:5432/app_db"
    )
    engine = MagicMock(spec=Engine)
    create_engine = Mock(return_value=engine)
    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: SimpleNamespace(database_url=database_url),
    )
    monkeypatch.setattr(session_module, "create_engine", create_engine)

    session_module.dispose_engine()
    create_engine.assert_not_called()

    assert session_module.get_engine() is engine
    session_module.get_session_factory()
    session_module.dispose_engine()

    engine.dispose.assert_called_once_with()
    assert session_module.get_engine.cache_info().currsize == 0
    assert session_module.get_session_factory.cache_info().currsize == 0
