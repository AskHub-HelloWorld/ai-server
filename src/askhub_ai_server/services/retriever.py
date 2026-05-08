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

    def _tokenize_query(self, query: str) -> str:
        """한국어 형태소 분석기가 활성화되어 있으면 BM25 질의를 토크나이즈한다."""
        if not self._settings.korean_tokenizer_enabled:
            return query
        try:
            from askhub_ai_server.services.korean_tokenizer import tokenize_for_search

            return tokenize_for_search(query)
        except Exception:
            return query

    def _bm25_search(
        self,
        query: str,
        team_id: int,
        top_k: int,
    ) -> list[RetrievedChunk]:
        """PostgreSQL tsvector 기반 BM25 키워드 검색."""
        tokenized_query = self._tokenize_query(query)
        tsquery = func.plainto_tsquery("simple", tokenized_query)
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

    def fetch_neighbor_chunks(
        self,
        chunks: list[RetrievedChunk],
        window: int = 1,
    ) -> dict[uuid.UUID, list[RetrievedChunk]]:
        """검색된 청크의 ±window 이웃 청크를 일괄 조회한다.

        Returns:
            dict mapping original chunk_id -> list of neighbor chunks (sorted by chunk_index).
        """
        if not chunks or window < 1:
            return {}

        # 이웃 조건 수집: (source_id, file_path, chunk_index) 목록
        original_keys: set[tuple[uuid.UUID, str, int]] = set()
        neighbor_conditions: list[tuple[uuid.UUID, str, int]] = []
        chunk_lookup: dict[tuple[uuid.UUID, str, int], uuid.UUID] = {}

        for chunk in chunks:
            key = (chunk.source_id, chunk.file_path, chunk.chunk_index)
            original_keys.add(key)
            for offset in range(-window, window + 1):
                if offset == 0:
                    continue
                neighbor_idx = chunk.chunk_index + offset
                if neighbor_idx < 0:
                    continue
                nkey = (chunk.source_id, chunk.file_path, neighbor_idx)
                if nkey not in original_keys:
                    neighbor_conditions.append(nkey)
                    chunk_lookup[nkey] = chunk.chunk_id

        if not neighbor_conditions:
            return {}

        # 일괄 조회를 위한 OR 조건 구성
        from sqlalchemy import and_, or_, literal

        or_clauses = []
        for source_id, file_path, chunk_index in set(neighbor_conditions):
            or_clauses.append(
                and_(
                    DocumentChunk.source_id == source_id,
                    DocumentChunk.file_path == file_path,
                    DocumentChunk.chunk_index == chunk_index,
                )
            )

        stmt = (
            select(
                DocumentChunk,
                RagSource.name.label("source_name"),
                RagSource.source_type.label("source_type"),
                RagSource.file_id.label("source_file_id"),
                literal(0.0).label("similarity"),
            )
            .join(RagSource, DocumentChunk.source_id == RagSource.id)
            .where(or_(*or_clauses))
        )

        results = self._db.execute(stmt).all()

        # 원본 청크 ID → 이웃 청크 리스트 매핑
        neighbor_map: dict[uuid.UUID, list[RetrievedChunk]] = {}
        for row in results:
            nkey = (row.DocumentChunk.source_id, row.DocumentChunk.file_path, row.DocumentChunk.chunk_index)
            neighbor_chunk = self._row_to_chunk(row)
            # 이 이웃이 어떤 원본 청크에 속하는지 찾기
            for chunk in chunks:
                if (
                    chunk.source_id == row.DocumentChunk.source_id
                    and chunk.file_path == row.DocumentChunk.file_path
                    and abs(chunk.chunk_index - row.DocumentChunk.chunk_index) <= window
                    and chunk.chunk_index != row.DocumentChunk.chunk_index
                ):
                    neighbor_map.setdefault(chunk.chunk_id, []).append(neighbor_chunk)

        # 이웃 청크를 chunk_index 순으로 정렬
        for chunk_id in neighbor_map:
            neighbor_map[chunk_id].sort(key=lambda c: c.chunk_index)

        return neighbor_map

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
