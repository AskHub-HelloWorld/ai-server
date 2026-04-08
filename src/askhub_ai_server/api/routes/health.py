from fastapi import APIRouter

from askhub_ai_server.core.config import get_settings
from askhub_ai_server.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        service=settings.app_name,
        environment=settings.app_env,
        version=settings.app_version,
        status="ok",
    )

