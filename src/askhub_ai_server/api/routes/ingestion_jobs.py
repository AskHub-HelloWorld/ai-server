"""인덱싱 작업 엔드포인트."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from askhub_ai_server.core.database import get_db
from askhub_ai_server.core.security import ServiceContext, get_service_context
from askhub_ai_server.models.document import IngestionJob
from askhub_ai_server.schemas.ingestion import (
    IngestionJobCreateRequest,
    IngestionJobResponse,
)
from askhub_ai_server.services.ingestion_job_service import IngestionJobService

router = APIRouter(prefix="/ingestion-jobs", tags=["ingestion-jobs"])


def _get_service(db: Annotated[Session, Depends(get_db)]) -> IngestionJobService:
    return IngestionJobService(db)


@router.post("", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
def create_ingestion_job(
    request: IngestionJobCreateRequest,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[IngestionJobService, Depends(_get_service)],
) -> IngestionJobResponse:
    job = service.create_job(request.source_id, request.mode, context.team_id)
    return _job_response(job)


@router.get("/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(
    job_id: UUID,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[IngestionJobService, Depends(_get_service)],
) -> IngestionJobResponse:
    job = service.get_job(job_id, context.team_id)
    return _job_response(job)


def _job_response(job: IngestionJob) -> IngestionJobResponse:
    return IngestionJobResponse(
        job_id=job.id,
        source_id=job.source_id,
        mode=job.mode,
        status=job.status,
        is_terminal=IngestionJobService.is_terminal(job),
        indexed_object_count=job.indexed_object_count,
        failure_reason=job.failure_reason,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
