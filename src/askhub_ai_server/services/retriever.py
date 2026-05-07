"""PgVector + BM25 하이브리드 RAG 검색 — RRF 합산."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
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
    """pgvector cosine similarity + BM25 하이브리드 검색 — team_id 기반 격리."""

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
        """하이브리드 검색: vector similarity + BM25, RRF 합산."""
        k = top_k or self._settings.rag_top_k
        retrieval_k = self._settings.rag_retrieval_k

        vector_results = self._vector_search(query, team_id, retrieval_k)

        if not self._settings.rag_bm25_enabled:
            return vector_results[:k]

        bm25_results = self._bm25_search(query, team_id, retrieval_k)
        fused = self._rrf_fuse(vector_results, bm25_results, k)

        logger.info(
            "하이브리드 검색 완료: query=%s, team_id=%d, vector=%d, bm25=%d, fused=%d",
            query[:50],
            team_id,
            len(vector_results),
            len(bm25_results),
            len(fused),
        )
        return fused

    def _vector_search(
        self,
        query: str,
        team_id: int,
        top_k: int,
    ) -> list[RetrievedChunk]:
        """cosine similarity 벡터 검색."""
        query_embedding = self._embedding.embed_text(query)
        threshold = self._settings.rag_similarity_threshold

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
            .limit(top_k)
        )

        results = self._db.execute(stmt).all()
        return [self._row_to_chunk(row) for row in results]

    def _bm25_search(
        self,
        query: str,
        team_id: int,
        top_k: int,
    ) -> list[RetrievedChunk]:
        """PostgreSQL tsvector 기반 BM25 키워드 검색."""
        tsquery = func.plainto_tsquery("simple", query)
        tsvector = func.to_tsvector(
            "simple",
            func.coalesce(DocumentChunk.search_text, DocumentChunk.content),
        )
        rank = func.ts_rank_cd(tsvector, tsquery).label("bm25_rank")

        stmt = (
            select(
                DocumentChunk,
                RagSource.name.label("source_name"),
                RagSource.source_type.label("source_type"),
                RagSource.file_id.label("source_file_id"),
                rank,
            )
            .join(RagSource, DocumentChunk.source_id == RagSource.id)
            .where(DocumentChunk.team_id == team_id)
            .where(tsvector.bool_op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(top_k)
        )

        results = self._db.execute(stmt).all()
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
                similarity=float(row.bm25_rank),
            )
            for row in results
        ]

    def _rrf_fuse(
        self,
        vector_results: list[RetrievedChunk],
        bm25_results: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Reciprocal Rank Fusion으로 두 결과를 합산한다."""
        rrf_k = self._settings.rag_rrf_k
        scores: dict[uuid.UUID, float] = {}
        chunk_map: dict[uuid.UUID, RetrievedChunk] = {}

        for rank, chunk in enumerate(vector_results, 1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0) + 1 / (rrf_k + rank)
            chunk_map[chunk.chunk_id] = chunk

        for rank, chunk in enumerate(bm25_results, 1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0) + 1 / (rrf_k + rank)
            if chunk.chunk_id not in chunk_map:
                chunk_map[chunk.chunk_id] = chunk

        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_k]
        return [chunk_map[cid] for cid in sorted_ids]

    @staticmethod
    def _row_to_chunk(row: Any) -> RetrievedChunk:
        return RetrievedChunk(
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
