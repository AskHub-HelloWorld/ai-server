from fastapi import APIRouter, HTTPException, status

from askhub_ai_server.schemas.ingestion import (
    IngestionJobCreateRequest,
    IngestionJobResponse,
)
from askhub_ai_server.services.in_memory_store import store

router = APIRouter(prefix="/ingestion-jobs", tags=["ingestion-jobs"])


@router.post("", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
def create_ingestion_job(request: IngestionJobCreateRequest) -> IngestionJobResponse:
    job = store.create_ingestion_job(request)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"source not found: {request.source_id}",
        )
    return job


@router.get("/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(job_id: str) -> IngestionJobResponse:
    job = store.get_ingestion_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ingestion job not found: {job_id}",
        )
    return job

