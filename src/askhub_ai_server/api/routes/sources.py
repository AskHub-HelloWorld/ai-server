from fastapi import APIRouter, status

from askhub_ai_server.schemas.source import SourceCreateRequest, SourceResponse
from askhub_ai_server.services.in_memory_store import store

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(request: SourceCreateRequest) -> SourceResponse:
    return store.create_source(request)

