"""Tests for the public health endpoint."""

import pytest
from httpx2 import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.main import app


@pytest.mark.anyio
async def test_health_check_returns_ok() -> None:
    """The process health endpoint returns its stable public contract."""
    test_settings = Settings(
        name="test-service",
        environment="test",
        version="test-version",
        debug=False,
        database_url=(
            "postgresql+psycopg://test_user:test_password@127.0.0.1:1/test_db"
        ),
        _env_file=None,
    )
    app.dependency_overrides[get_settings] = lambda: test_settings

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "ok",
        "service": "test-service",
        "environment": "test",
        "version": "test-version",
    }
