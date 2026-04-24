"""소스 요약 생성 서비스 — worker에서 분리."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from askhub_ai_server.models.document import DocumentChunk, RagSource
from askhub_ai_server.models.enums import SourceType
from askhub_ai_server.services.llm import get_llm_service

logger = logging.getLogger(__name__)

_MAX_SUMMARY_CHUNKS = 20
_MAX_DIRECT_CHUNKS = 5
_MAX_TEXT_LEN = 8000
_MAX_SAMPLED_FILES = 15

# 핵심 파일 판별 패턴 (우선 샘플링 대상)
_PRIORITY_KEYWORDS = (
    "readme", "main", "app", "index", "server", "setup",
    "config", "settings", "package.json", "pyproject.toml",
    "cargo.toml", "go.mod", "pom.xml", "build.gradle",
    "dockerfile", "docker-compose", "makefile", "requirements",
)


def generate_source_summary(db: Session, source: RagSource) -> str | None:
    """소스 타입에 따라 적합한 요약 전략을 선택한다."""
    if source.source_type == SourceType.REPOSITORY:
        return _generate_repo_summary(db, source)
    return _generate_document_summary(db, source)


def _generate_document_summary(db: Session, source: RagSource) -> str | None:
    """문서 소스: 순차 청크를 map-reduce로 요약한다."""
    llm = get_llm_service()

    chunks = list(
        db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.source_id == source.id)
            .order_by(DocumentChunk.chunk_index)
            .limit(_MAX_SUMMARY_CHUNKS)
        ).all()
    )
    if not chunks:
        return None

    if len(chunks) <= _MAX_DIRECT_CHUNKS:
        combined = "\n\n".join(c.content for c in chunks)
        return llm.summarize(combined[:_MAX_TEXT_LEN])

    # Map phase: _MAX_DIRECT_CHUNKS개씩 묶어 부분 요약
    partial_summaries: list[str] = []
    for i in range(0, len(chunks), _MAX_DIRECT_CHUNKS):
        batch_text = "\n\n".join(c.content for c in chunks[i : i + _MAX_DIRECT_CHUNKS])
        partial = llm.summarize(batch_text[:_MAX_TEXT_LEN])
        partial_summaries.append(partial)

    # Reduce phase: 부분 요약을 합쳐 최종 요약
    combined_summaries = "\n\n".join(partial_summaries)
    return llm.summarize(combined_summaries[:_MAX_TEXT_LEN])


def _generate_repo_summary(db: Session, source: RagSource) -> str | None:
    """리포지토리 소스: 파일 트리 + 파일별 대표 청크 기반 요약."""
    llm = get_llm_service()

    # 1) 소스의 모든 고유 파일 경로 수집
    all_paths: list[str] = list(
        db.scalars(
            select(DocumentChunk.file_path)
            .where(DocumentChunk.source_id == source.id)
            .distinct()
            .order_by(DocumentChunk.file_path)
        ).all()
    )
    if not all_paths:
        return None

    # 2) 파일 트리 구성 (최대 80줄로 제한)
    file_tree = "\n".join(all_paths[:80])
    if len(all_paths) > 80:
        file_tree += f"\n... 외 {len(all_paths) - 80}개 파일"

    # 3) 핵심 파일 우선 샘플링 + 나머지 균등 분산
    sampled_paths = _select_representative_files(all_paths, _MAX_SAMPLED_FILES)

    # 4) 각 파일의 첫 번째 청크 가져오기
    sample_texts: list[str] = []
    for path in sampled_paths:
        chunk = db.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.source_id == source.id,
                DocumentChunk.file_path == path,
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(1)
        ).first()
        if chunk is not None:
            preview = chunk.content[:600]
            sample_texts.append(f"### {path}\n```\n{preview}\n```")

    # 5) LLM 입력 조합: 파일 트리 + 코드 샘플
    llm_input = (
        f"## 파일 구조 ({len(all_paths)}개 파일)\n"
        f"{file_tree}\n\n"
        f"## 주요 파일 코드 샘플\n\n"
        + "\n\n".join(sample_texts)
    )
    return llm.summarize_codebase(llm_input[:_MAX_TEXT_LEN])


def _select_representative_files(
    all_paths: list[str],
    max_files: int,
) -> list[str]:
    """핵심 파일을 우선 선택하고, 나머지를 균등 분산 샘플링한다."""
    priority: list[str] = []
    remaining: list[str] = []

    for path in all_paths:
        lower = path.lower().rsplit("/", 1)[-1]  # 파일명만 비교
        if any(kw in lower for kw in _PRIORITY_KEYWORDS):
            priority.append(path)
        else:
            remaining.append(path)

    selected = priority[:max_files]
    slots_left = max_files - len(selected)

    if slots_left > 0 and remaining:
        # 균등 분산: 전체에서 고르게 뽑기
        step = max(1, len(remaining) // slots_left)
        for i in range(0, len(remaining), step):
            if len(selected) >= max_files:
                break
            selected.append(remaining[i])

    return selected
