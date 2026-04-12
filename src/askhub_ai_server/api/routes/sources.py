from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from askhub_ai_server.core.database import get_db
from askhub_ai_server.core.security import ServiceContext, get_service_context
from askhub_ai_server.models.document import RagSource
from askhub_ai_server.schemas.source import SourceCreateRequest, SourceResponse

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(
    request: SourceCreateRequest,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    db: Annotated[Session, Depends(get_db)],
) -> SourceResponse:
    if context.team_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="team context is required to register a RAG source",
        )

    source = RagSource(
        source_type=request.source_type,
        name=request.name,
        team_id=context.team_id,
        repo_url=request.repo_url,
        default_branch=request.default_branch,
        url=request.url,
        status="registered",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_response(source)


def _source_response(source: RagSource) -> SourceResponse:
    return SourceResponse(
        source_id=source.id,
        source_type=source.source_type,
        name=source.name,
        team_id=source.team_id,
        status=source.status,
        repo_url=source.repo_url,
        default_branch=source.default_branch,
        url=source.url,
        created_at=source.created_at,
    )
