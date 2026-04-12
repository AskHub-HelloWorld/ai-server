from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from askhub_ai_server.core.database import get_db
from askhub_ai_server.core.security import ServiceContext, get_service_context
from askhub_ai_server.models.document import IngestionJob, RagSource
from askhub_ai_server.schemas.ingestion import (
    IngestionJobCreateRequest,
    IngestionJobResponse,
)

router = APIRouter(prefix="/ingestion-jobs", tags=["ingestion-jobs"])


@router.post("", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
def create_ingestion_job(
    request: IngestionJobCreateRequest,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    db: Annotated[Session, Depends(get_db)],
) -> IngestionJobResponse:
    source = db.get(RagSource, request.source_id)
    if source is None or source.team_id != context.team_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"source not found: {request.source_id}",
        )
    job = IngestionJob(
        source_id=source.id,
        mode=request.mode,
        status="queued",
        indexed_object_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_response(job)


@router.get("/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(
    job_id: UUID,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    db: Annotated[Session, Depends(get_db)],
) -> IngestionJobResponse:
    job = db.get(IngestionJob, job_id)
    if job is None or job.source.team_id != context.team_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ingestion job not found: {job_id}",
        )
    return _job_response(job)


def _job_response(job: IngestionJob) -> IngestionJobResponse:
    return IngestionJobResponse(
        job_id=job.id,
        source_id=job.source_id,
        mode=job.mode,
        status=job.status,
        indexed_object_count=job.indexed_object_count,
        failure_reason=job.failure_reason,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
