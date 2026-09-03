"""Tests for environment-specific FastAPI application behavior."""

import pytest
from httpx2 import ASGITransport, AsyncClient
from pydantic import ValidationError

import app.main as main_module
from app.core.config import Settings


DOCUMENTATION_PATHS = {
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}
VALID_DATABASE_URL = (
    "postgresql+psycopg://test_user:test_password@127.0.0.1:1/test_db"
)


def test_application_configuration_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application creation fails validation when its required DSN is absent."""
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: Settings(_env_file=None),
    )

    with pytest.raises(ValidationError) as exc_info:
        main_module.create_app()

    assert exc_info.value.errors()[0]["loc"] == ("database_url",)
    assert exc_info.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize(
    ("environment", "documentation_enabled"),
    [
        ("local", True),
        ("development", True),
        ("test", False),
        ("production", False),
    ],
)
def test_documentation_routes_follow_environment(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    documentation_enabled: bool,
) -> None:
    """Generated API documentation is limited to interactive environments."""
    settings = Settings(
        environment=environment,
        debug=False,
        database_url=VALID_DATABASE_URL,
        _env_file=None,
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    application = main_module.create_app()
    route_paths = {
        route.path for route in application.routes if hasattr(route, "path")
    }

    if documentation_enabled:
        assert DOCUMENTATION_PATHS <= route_paths
        assert application.docs_url == "/docs"
        assert application.redoc_url == "/redoc"
        assert application.openapi_url == "/openapi.json"
    else:
        assert DOCUMENTATION_PATHS.isdisjoint(route_paths)
        assert application.docs_url is None
        assert application.redoc_url is None
        assert application.openapi_url is None


@pytest.mark.anyio
async def test_documentation_routes_are_not_reachable_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production returns 404 for every generated documentation URL."""
    settings = Settings(
        environment="production",
        debug=False,
        database_url=VALID_DATABASE_URL,
        _env_file=None,
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    application = main_module.create_app()

    transport = ASGITransport(app=application)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        responses = [await client.get(path) for path in DOCUMENTATION_PATHS]

    assert all(response.status_code == 404 for response in responses)
