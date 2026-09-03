"""Application health endpoint."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Public health-check response."""

    status: Literal["ok"]
    service: str
    environment: str
    version: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check whether the API process is healthy",
)
async def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Return process-level health without exposing sensitive configuration."""
    return HealthResponse(
        status="ok",
        service=settings.name,
        environment=settings.environment,
        version=settings.version,
    )

