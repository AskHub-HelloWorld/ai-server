"""PgVector 기반 RAG 검색 — cosine similarity + team_id 필터."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import Settings
from askhub_ai_server.models.document import DocumentChunk, RagSource
from askhub_ai_server.services.embedding import BedrockEmbeddingService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedChunk:
    """검색된 문서 청크 + 유사도 점수."""

    chunk_id: uuid.UUID
    content: str
    file_path: str
    file_type: str | None
    line_start: int | None
    line_end: int | None
    chunk_index: int
    metadata: dict[str, Any]
    commit_sha: str | None
    repo_url: str | None
    source_id: uuid.UUID
    source_name: str
    source_type: str
    source_file_id: uuid.UUID | None
    similarity: float


class PgVectorRetriever:
    """pgvector cosine similarity 검색 — team_id 기반 격리."""

    def __init__(
        self,
        db: Session,
        embedding_service: BedrockEmbeddingService,
        settings: Settings,
    ) -> None:
        self._db = db
        self._embedding = embedding_service
        self._settings = settings

    def search(
        self,
        query: str,
        team_id: int,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """쿼리 텍스트를 임베딩 후 cosine similarity 검색을 수행한다."""
        query_embedding = self._embedding.embed_text(query)
        k = top_k or self._settings.rag_top_k
        threshold = self._settings.rag_similarity_threshold

        # cosine_distance: 0 = identical, 2 = opposite
        # similarity = 1 - cosine_distance
        cosine_dist = DocumentChunk.embedding.cosine_distance(query_embedding)
        similarity_expr = (1 - cosine_dist).label("similarity")

        stmt = (
            select(
                DocumentChunk,
                RagSource.name.label("source_name"),
                RagSource.source_type.label("source_type"),
                RagSource.file_id.label("source_file_id"),
                similarity_expr,
            )
            .join(RagSource, DocumentChunk.source_id == RagSource.id)
            .where(DocumentChunk.team_id == team_id)
            .where((1 - cosine_dist) >= threshold)
            .order_by(cosine_dist)
            .limit(k)
        )

        results = self._db.execute(stmt).all()
        logger.info(
            "RAG 검색 완료: query=%s, team_id=%d, results=%d",
            query[:50],
            team_id,
            len(results),
        )
        return [
            RetrievedChunk(
                chunk_id=row.DocumentChunk.id,
                content=row.DocumentChunk.content,
                file_path=row.DocumentChunk.file_path,
                file_type=row.DocumentChunk.file_type,
                line_start=row.DocumentChunk.line_start,
                line_end=row.DocumentChunk.line_end,
                chunk_index=row.DocumentChunk.chunk_index,
                metadata=row.DocumentChunk.metadata_json or {},
                commit_sha=row.DocumentChunk.commit_sha,
                repo_url=row.DocumentChunk.repo_url,
                source_id=row.DocumentChunk.source_id,
                source_name=row.source_name,
                source_type=row.source_type,
                source_file_id=row.source_file_id,
                similarity=row.similarity,
            )
            for row in results
        ]
