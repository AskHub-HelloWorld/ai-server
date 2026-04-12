from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from askhub_ai_server.core.config import get_settings
from askhub_ai_server.core.database import SessionLocal
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


@router.get("/ready", response_model=HealthResponse)
def ready() -> HealthResponse:
    settings = get_settings()
    failures: list[str] = []

    if settings.service_auth_enabled and not settings.service_auth_secret:
        failures.append("service authentication secret is missing")
    if not settings.aws_region:
        failures.append("AWS region is missing")
    if not settings.bedrock_model_id:
        failures.append("Bedrock model id is missing")
    if settings.file_storage_backend.strip().lower() == "s3" and not settings.s3_bucket:
        failures.append("S3 bucket is missing")

    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        failures.append("database is not reachable")

    if failures:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=failures,
        )

    return HealthResponse(
        service=settings.app_name,
        environment=settings.app_env,
        version=settings.app_version,
        status="ready",
    )
