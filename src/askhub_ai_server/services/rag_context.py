"""RAG context 빌더 — 검색된 청크를 LLM context와 Citation으로 변환."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from askhub_ai_server.models.enums import SourceType
from askhub_ai_server.services.chunker import estimate_tokens
from askhub_ai_server.services.retriever import PgVectorRetriever, RetrievedChunk

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONTEXT_TOKENS = 4000

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_RAG_CONTEXT_INSTRUCTIONS = (_PROMPTS_DIR / "rag_context_instructions.txt").read_text(
    encoding="utf-8",
).strip()


@dataclass(frozen=True)
class RagContext:
    """RAG 검색 결과를 LLM context + Citation으로 변환한 결과."""

    text: str
    citations: list[dict]
    chunks: list[RetrievedChunk] = field(default_factory=list)
    answerable: bool = False


class QueryRewriter(Protocol):
    def rewrite_for_retrieval(self, query: str) -> str:
        """사용자 질문을 검색 질의로 재작성한다."""


class CitationBuilder:
    """검색된 청크 메타데이터를 Citation 스키마로 변환한다.

    각 citation에는 ``index`` 필드(1-based)가 포함되어
    LLM 응답의 인라인 인용 ``[N]``과 매핑된다.
    """

    @staticmethod
    def build(chunks: list[RetrievedChunk]) -> list[dict]:
        deduped_chunks = CitationBuilder.deduplicate(chunks)
        citations: list[dict] = []
        for idx, chunk in enumerate(deduped_chunks, 1):
            source_type = chunk.source_type
            file_id = str(chunk.source_file_id) if chunk.source_file_id else None
            url: str | None = None
            repo = chunk.repo_url if source_type == SourceType.REPOSITORY else None

            if source_type == SourceType.REPOSITORY and chunk.repo_url and chunk.commit_sha:
                repo_url = chunk.repo_url.rstrip("/")
                if repo_url.endswith(".git"):
                    repo_url = repo_url[:-4]
                url = f"{repo_url}/blob/{chunk.commit_sha}/{chunk.file_path}"
                if chunk.line_start is not None:
                    url += f"#L{chunk.line_start}"
                    if chunk.line_end is not None:
                        url += f"-L{chunk.line_end}"
            elif source_type == SourceType.DOCUMENT and file_id:
                url = f"/v1/files/{file_id}/download"

            is_external = bool(url and not url.startswith("/v1/"))

            if is_external:
                viewer_type = "external"
            elif chunk.file_path and chunk.file_path.lower().endswith(".pdf"):
                viewer_type = "pdf"
            else:
                viewer_type = "text"

            citations.append({
                "index": idx,
                "title": chunk.file_path,
                "source_type": source_type,
                "path": chunk.file_path,
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "chunk_index": chunk.chunk_index,
                "page": chunk.metadata.get("page"),
                "heading": chunk.metadata.get("heading"),
                "section": chunk.metadata.get("section"),
                "symbol_name": chunk.metadata.get("symbol_name"),
                "symbol_type": chunk.metadata.get("symbol_type"),
                "route_path": chunk.metadata.get("route_path"),
                "language": chunk.metadata.get("language"),
                "commit_sha": chunk.commit_sha,
                "repo": repo,
                "file_id": file_id,
                "url": url,
                "is_external": is_external,
                "viewer_type": viewer_type,
            })
        return citations

    @staticmethod
    def deduplicate(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        seen_keys: set[tuple] = set()
        deduped: list[RetrievedChunk] = []
        for chunk in chunks:
            # 같은 파일의 같은 범위가 중복되지 않도록 deduplicate
            key = (
                chunk.source_id,
                chunk.file_path,
                chunk.line_start,
                chunk.line_end,
                chunk.chunk_index,
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(chunk)
        return deduped


class RagContextBuilder:
    """PgVectorRetriever를 사용하여 RAG context를 구성한다."""

    def __init__(
        self,
        retriever: PgVectorRetriever,
        *,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        query_rewriter: QueryRewriter | None = None,
        answerable_threshold: float = 0.5,
    ) -> None:
        self._retriever = retriever
        self._max_context_tokens = max_context_tokens
        self._query_rewriter = query_rewriter
        self._answerable_threshold = answerable_threshold

    def build(self, query: str, team_id: int | None) -> RagContext:
        """사용자 질문으로 관련 청크를 검색하고 LLM context + Citation을 구성한다."""
        if team_id is None:
            return RagContext(text="", citations=[], chunks=[])

        retrieval_queries = self._retrieval_queries(query)
        chunks = self._search_all(retrieval_queries, team_id)
        if not chunks:
            logger.info(
                "RAG 검색 결과 없음: query=%s, retrieval_queries=%s, team_id=%d",
                query[:50],
                [q[:80] for q in retrieval_queries],
                team_id,
            )
            return RagContext(text="", citations=[], chunks=[])

        selected_chunks = self._limit_chunks_by_tokens(CitationBuilder.deduplicate(chunks))
        if not selected_chunks:
            return RagContext(text="", citations=[], chunks=[])

        context_text = self._format_context(selected_chunks)
        citations = CitationBuilder.build(selected_chunks)

        best_similarity = max(c.similarity for c in selected_chunks)
        answerable = best_similarity >= self._answerable_threshold

        logger.info(
            "RAG context 구성 완료: chunks=%d, citations=%d, best_sim=%.3f, answerable=%s",
            len(selected_chunks),
            len(citations),
            best_similarity,
            answerable,
        )
        return RagContext(
            text=context_text,
            citations=citations,
            chunks=selected_chunks,
            answerable=answerable,
        )

    def _retrieval_queries(self, query: str) -> list[str]:
        if self._query_rewriter is None:
            return [query]
        try:
            rewritten = self._query_rewriter.rewrite_for_retrieval(query).strip()
        except Exception:
            logger.warning("RAG 검색 질의 재작성 실패 — 원 질문으로 검색", exc_info=True)
            return [query]
        if not rewritten:
            return [query]
        queries = [query]
        if rewritten.casefold() != query.casefold():
            queries.append(rewritten)
        logger.info("RAG 검색 질의 재작성: %s -> %s", query[:80], rewritten[:120])
        return queries

    def _search_all(self, queries: list[str], team_id: int) -> list[RetrievedChunk]:
        merged: dict[tuple, RetrievedChunk] = {}
        for query in queries:
            for chunk in self._retriever.search(query, team_id):
                key = (
                    chunk.source_id,
                    chunk.file_path,
                    chunk.line_start,
                    chunk.line_end,
                    chunk.chunk_index,
                )
                current = merged.get(key)
                if current is None or chunk.similarity > current.similarity:
                    merged[key] = chunk
        return sorted(merged.values(), key=lambda chunk: chunk.similarity, reverse=True)

    def _limit_chunks_by_tokens(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        budget = max(self._max_context_tokens, 1)
        selected: list[RetrievedChunk] = []
        used = 0
        for chunk in chunks:
            estimated = estimate_tokens(chunk.content) + 20
            if selected and used + estimated > budget:
                break
            selected.append(chunk)
            used += estimated
            if used >= budget:
                break
        return selected

    @staticmethod
    def _format_context(chunks: list[RetrievedChunk]) -> str:
        """검색된 청크를 '[참고자료 N]' 형식의 LLM 입력 텍스트로 변환한다."""
        parts: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            header = f"[참고자료 {i}] {chunk.source_name} — {chunk.file_path}"
            if chunk.line_start is not None:
                header += f" (lines {chunk.line_start}"
                if chunk.line_end is not None:
                    header += f"–{chunk.line_end}"
                header += ")"
            details = _metadata_details(chunk)
            if details:
                header += f" [{', '.join(details)}]"
            parts.append(f"{header}\n원문:\n{chunk.content}")

        return _RAG_CONTEXT_INSTRUCTIONS + "\n\n" + "\n\n---\n\n".join(parts)


def _metadata_details(chunk: RetrievedChunk) -> list[str]:
    details: list[str] = []
    page = chunk.metadata.get("page")
    if page:
        details.append(f"page {page}")
    heading = chunk.metadata.get("heading")
    if heading:
        details.append(f"heading: {heading}")
    symbol = chunk.metadata.get("symbol_name")
    symbol_type = chunk.metadata.get("symbol_type")
    if symbol:
        label = f"{symbol_type}: {symbol}" if symbol_type else f"symbol: {symbol}"
        details.append(label)
    route = chunk.metadata.get("route_path")
    if route:
        details.append(f"route: {route}")
    return details
