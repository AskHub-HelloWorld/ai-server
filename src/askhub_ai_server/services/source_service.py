"""RAG 소스 관리 서비스 — DB 조회/저장 로직을 route에서 분리."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from askhub_ai_server.core.security import ServiceContext
from askhub_ai_server.models.document import DocumentChunk, RagSource
from askhub_ai_server.models.enums import FilePurpose, SourceStatus
from askhub_ai_server.models.file import UserFile
from askhub_ai_server.schemas.source import SourceCreateRequest, SourceResponse
from askhub_ai_server.services.exceptions import ServiceError

_STATUS_LABELS: dict[str, str] = {
    SourceStatus.REGISTERED: "등록됨",
    SourceStatus.INDEXING: "⏳ 인덱싱",
    SourceStatus.READY: "✓ 사용 가능",
    SourceStatus.ERROR: "⚠ 오류",
}

_TYPE_LABELS: dict[str, str] = {
    "repository": "레포",
    "document": "문서",
}


class SourceService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_source(
        self, request: SourceCreateRequest, context: ServiceContext,
    ) -> RagSource:
        if context.team_id is None:
            raise ServiceError(400, "team context is required to register a RAG source")

        if request.source_type == "document":
            self._require_owned_rag_source_file(request.file_id, context)

        name = request.name
        if not name:
            if request.source_type == "repository" and request.repo_url:
                name = re.sub(r"^https?://", "", request.repo_url)
                name = re.sub(r"\.git$", "", name)
            elif request.source_type == "document" and request.file_id:
                user_file = self._db.get(UserFile, request.file_id)
                name = user_file.filename if user_file else str(request.file_id)
            else:
                name = "unnamed"

        source = RagSource(
            source_type=request.source_type,
            name=name,
            team_id=context.team_id,
            repo_url=request.repo_url,
            default_branch=request.default_branch,
            url=request.url,
            file_id=request.file_id,
            status=SourceStatus.REGISTERED,
        )
        self._db.add(source)
        self._db.commit()
        self._db.refresh(source)
        return source

    def list_sources(self, context: ServiceContext) -> list[tuple[RagSource, int]]:
        if context.team_id is None:
            raise ServiceError(400, "team context is required to list RAG sources")

        chunk_count = func.count(DocumentChunk.id).label("chunk_count")
        stmt = (
            select(RagSource, chunk_count)
            .outerjoin(DocumentChunk, DocumentChunk.source_id == RagSource.id)
            .where(RagSource.team_id == context.team_id)
            .group_by(RagSource.id)
            .order_by(RagSource.created_at.desc(), RagSource.id.desc())
        )
        return list(self._db.execute(stmt).all())

    def delete_source(self, source_id: UUID, context: ServiceContext) -> None:
        source = self._db.get(RagSource, source_id)
        if source is None or source.team_id != context.team_id:
            raise ServiceError(404, f"source not found: {source_id}")
        self._db.delete(source)
        self._db.commit()

    def _require_owned_rag_source_file(
        self, file_id: UUID | None, context: ServiceContext,
    ) -> UserFile:
        if file_id is None:
            raise ServiceError(422, "file_id is required")
        user_file = self._db.get(UserFile, file_id)
        if (
            user_file is None
            or user_file.user_id != context.user_id
            or user_file.team_id != context.team_id
            or user_file.purpose != FilePurpose.RAG_SOURCE
        ):
            raise ServiceError(404, f"file not found: {file_id}")
        return user_file

    @staticmethod
    def to_response(source: RagSource, *, chunk_count: int = 0) -> SourceResponse:
        return SourceResponse(
            source_id=source.id,
            source_type=source.source_type,
            name=source.name,
            team_id=source.team_id,
            status=source.status,
            status_label=_STATUS_LABELS.get(source.status, source.status),
            type_label=_TYPE_LABELS.get(source.source_type, source.source_type),
            repo_url=source.repo_url,
            default_branch=source.default_branch,
            url=source.url,
            file_id=source.file_id,
            summary=source.summary,
            chunk_count=chunk_count,
            created_at=source.created_at,
        )
