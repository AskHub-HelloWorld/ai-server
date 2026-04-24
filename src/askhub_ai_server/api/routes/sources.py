"""RAG 소스 관리 엔드포인트."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from askhub_ai_server.core.database import get_db
from askhub_ai_server.core.security import ServiceContext, get_service_context
from askhub_ai_server.schemas.source import (
    SourceCreateRequest,
    SourceListResponse,
    SourceResponse,
)
from askhub_ai_server.services.exceptions import ServiceError
from askhub_ai_server.services.source_service import SourceService

router = APIRouter(prefix="/sources", tags=["sources"])


def _get_source_service(
    db: Annotated[Session, Depends(get_db)],
) -> SourceService:
    return SourceService(db)


def _http_exception(error: ServiceError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(
    request: SourceCreateRequest,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[SourceService, Depends(_get_source_service)],
) -> SourceResponse:
    try:
        source = service.create_source(request, context)
    except ServiceError as exc:
        raise _http_exception(exc) from exc
    return SourceService.to_response(source)


@router.get("", response_model=SourceListResponse)
def list_sources(
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[SourceService, Depends(_get_source_service)],
) -> SourceListResponse:
    try:
        rows = service.list_sources(context)
    except ServiceError as exc:
        raise _http_exception(exc) from exc
    return SourceListResponse(
        sources=[
            SourceService.to_response(source, chunk_count=int(count or 0))
            for source, count in rows
        ]
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: UUID,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[SourceService, Depends(_get_source_service)],
) -> None:
    try:
        service.delete_source(source_id, context)
    except ServiceError as exc:
        raise _http_exception(exc) from exc
