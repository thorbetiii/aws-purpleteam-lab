"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import get_settings
from app.db.session import dispose_engine


@asynccontextmanager
async def application_lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Release pooled database connections when the application stops."""
    try:
        yield
    finally:
        dispose_engine()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    documentation_enabled = settings.environment in {"local", "development"}

    application = FastAPI(
        title=settings.name,
        version=settings.version,
        debug=settings.debug,
        lifespan=application_lifespan,
        docs_url="/docs" if documentation_enabled else None,
        redoc_url="/redoc" if documentation_enabled else None,
        openapi_url="/openapi.json" if documentation_enabled else None,
        swagger_ui_oauth2_redirect_url=(
            "/docs/oauth2-redirect" if documentation_enabled else None
        ),
    )
    application.include_router(health_router)

    return application


app = create_app()
