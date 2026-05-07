"""Ingestion Worker — RAG 소스를 청킹·임베딩하여 document_chunks에 저장한다."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import Settings, get_settings
from askhub_ai_server.core.database import SessionLocal
from askhub_ai_server.models.document import DocumentChunk, IngestionJob, RagSource
from askhub_ai_server.models.enums import (
    FilePurpose,
    JobMode,
    JobStatus,
    SourceStatus,
    SourceType,
)
from askhub_ai_server.models.file import UserFile
from askhub_ai_server.services.chunker import Chunk, chunk_text, estimate_tokens
from askhub_ai_server.services.embedding import BedrockEmbeddingService, get_embedding_service
from askhub_ai_server.services.file_storage import get_file_storage
from askhub_ai_server.services.loaders.document_loader import load_document_as_markdown
from askhub_ai_server.services.loaders.github_loader import load_repository

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
CHUNK_BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# PendingChunk — 임베딩 전 청크 + 소스별 메타데이터
# ---------------------------------------------------------------------------

@dataclass
class PendingChunk:
    """임베딩 전 청크와 소스별 추가 메타데이터."""

    chunk: Chunk
    commit_sha: str | None = None
    repo_url: str | None = None


# ---------------------------------------------------------------------------
# 공통: 배치 임베딩 + DB 저장
# ---------------------------------------------------------------------------

def _embed_and_store(
    db: Session,
    pending: list[PendingChunk],
    source: RagSource,
    job: IngestionJob,
    embedding_service: BedrockEmbeddingService,
) -> int:
    """청크를 배치 임베딩하여 document_chunks에 저장한다."""
    total = 0
    for i in range(0, len(pending), CHUNK_BATCH_SIZE):
        batch = pending[i : i + CHUNK_BATCH_SIZE]
        texts = [p.chunk.embedding_text or p.chunk.content for p in batch]
        embeddings = embedding_service.embed_batch(texts)

        doc_chunks = []
        for p, emb in zip(batch, embeddings, strict=True):
            doc_chunks.append(
                DocumentChunk(
                    source_id=source.id,
                    job_id=job.id,
                    team_id=source.team_id,
                    content=p.chunk.content,
                    embedding_text=p.chunk.embedding_text or p.chunk.content,
                    search_text=p.chunk.search_text or p.chunk.embedding_text or p.chunk.content,
                    metadata_json=p.chunk.metadata,
                    token_count=estimate_tokens(p.chunk.content),
                    file_path=p.chunk.file_path,
                    file_type=p.chunk.file_type,
                    line_start=p.chunk.line_start,
                    line_end=p.chunk.line_end,
                    chunk_index=p.chunk.chunk_index,
                    commit_sha=p.commit_sha,
                    repo_url=p.repo_url,
                    embedding=emb,
                )
            )
        db.add_all(doc_chunks)
        db.flush()
        total += len(doc_chunks)
        logger.info("배치 저장: %d chunks (total=%d)", len(doc_chunks), total)
    return total


# ---------------------------------------------------------------------------
# Worker 메인 루프
# ---------------------------------------------------------------------------

def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    embedding_service = get_embedding_service()

    logger.info("Ingestion worker 시작")
    while True:
        try:
            job = _claim_next_job()
            if job is None:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            _process_job(job, embedding_service, settings)
        except KeyboardInterrupt:
            logger.info("Worker 종료 요청")
            break
        except Exception:
            logger.exception("Worker 루프 예외 발생")
            time.sleep(POLL_INTERVAL_SECONDS)


def _claim_next_job() -> IngestionJob | None:
    """가장 오래된 queued job을 원자적으로 claim한다 (SELECT FOR UPDATE SKIP LOCKED)."""
    with SessionLocal() as db:
        stmt = (
            select(IngestionJob)
            .where(IngestionJob.status == JobStatus.QUEUED)
            .order_by(IngestionJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = db.scalars(stmt).first()
        if job is None:
            return None

        job.status = JobStatus.RUNNING
        source = db.get(RagSource, job.source_id)
        if source is not None:
            source.status = SourceStatus.INDEXING

        db.commit()
        db.refresh(job)
        logger.info("Job claimed: %s (source=%s)", job.id, job.source_id)
        return job


def _process_job(
    job: IngestionJob,
    embedding_service: BedrockEmbeddingService,
    settings: Settings,
) -> None:
    """소스 로드 → 청킹 → 임베딩 → DB 저장."""
    with SessionLocal() as db:
        source = db.get(RagSource, job.source_id)
        job = db.merge(job)
        if source is None:
            job.status = JobStatus.FAILED
            job.failure_reason = "source not found"
            db.commit()
            return

        try:
            if job.mode == JobMode.FULL:
                # full 모드: 기존 청크 전부 삭제 후 새로 생성
                db.query(DocumentChunk).filter(
                    DocumentChunk.source_id == source.id,
                ).delete(synchronize_session=False)
                db.flush()

            total_chunks = 0

            if source.source_type == SourceType.REPOSITORY:
                total_chunks = _process_repository(
                    db, source, job, embedding_service,
                )
            elif source.source_type == SourceType.DOCUMENT:
                total_chunks = _process_document_source(
                    db, source, job, embedding_service, settings,
                )
            else:
                raise ValueError(f"알 수 없는 source_type: {source.source_type}")

            # 요약 생성 (실패해도 인제스션은 정상 완료)
            try:
                from askhub_ai_server.services.summary_service import (
                    generate_source_summary,
                )

                summary = generate_source_summary(db, source)
                source.summary = summary
            except Exception:
                logger.warning("요약 생성 실패: source=%s", source.id, exc_info=True)

            job.status = JobStatus.SUCCEEDED
            job.indexed_object_count = total_chunks
            source.status = SourceStatus.READY
            db.commit()
            logger.info(
                "Job 완료: %s, chunks=%d", job.id, total_chunks,
            )

        except Exception as exc:
            db.rollback()
            # 실패 상태 기록은 별도 세션으로
            _mark_job_failed(job.id, source.id, str(exc)[:2000])
            logger.exception("Job 실패: %s", job.id)


# ---------------------------------------------------------------------------
# 소스 타입별 처리
# ---------------------------------------------------------------------------

def _process_repository(
    db: Session,
    source: RagSource,
    job: IngestionJob,
    embedding_service: BedrockEmbeddingService,
) -> int:
    """GitHub 리포지토리를 클론하고 코드 파일을 청킹·임베딩한다."""
    if not source.repo_url:
        raise ValueError("repo_url이 비어 있습니다")

    pending: list[PendingChunk] = []
    for loaded_file in load_repository(source.repo_url, source.default_branch):
        file_chunks = chunk_text(
            loaded_file.content,
            loaded_file.path,
            source_title=source.name,
            document_summary=_summarize_for_indexing(loaded_file.content),
        )
        for chunk in file_chunks:
            pending.append(
                PendingChunk(
                    chunk=chunk,
                    commit_sha=loaded_file.commit_sha,
                    repo_url=loaded_file.repo_url,
                )
            )

    return _embed_and_store(db, pending, source, job, embedding_service)


def _process_document_source(
    db: Session,
    source: RagSource,
    job: IngestionJob,
    embedding_service: BedrockEmbeddingService,
    settings: Settings,
) -> int:
    """S3에 저장된 문서 파일을 텍스트 추출·청킹·임베딩한다."""
    storage = get_file_storage(settings)

    if source.file_id is None:
        logger.warning("document source에 file_id가 없음: source=%s", source.id)
        return 0

    user_file = db.get(UserFile, source.file_id)
    if (
        user_file is None
        or user_file.team_id != source.team_id
        or user_file.purpose != FilePurpose.RAG_SOURCE
    ):
        logger.warning("연결된 파일 없음: source=%s", source.id)
        return 0

    try:
        data = storage.read_bytes(user_file, settings.max_upload_bytes)
    except Exception:
        logger.warning("파일 읽기 실패: %s", user_file.id, exc_info=True)
        return 0

    loaded = load_document_as_markdown(data, user_file.filename)
    if loaded is None:
        return 0

    pending: list[PendingChunk] = []
    document_summary = _summarize_for_indexing(loaded.content)
    file_chunks = chunk_text(
        loaded.content,
        loaded.file_path,
        source_title=source.name or loaded.title,
        document_summary=document_summary,
        is_markdown=True,
    )
    file_chunks = [replace(chunk, chunk_index=index) for index, chunk in enumerate(file_chunks)]
    for chunk in file_chunks:
        pending.append(PendingChunk(chunk=chunk))

    return _embed_and_store(db, pending, source, job, embedding_service)


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def _mark_job_failed(job_id: uuid.UUID, source_id: uuid.UUID, reason: str) -> None:
    """별도 DB 세션으로 job 실패 상태를 기록한다."""
    with SessionLocal() as db:
        job = db.get(IngestionJob, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.failure_reason = reason
        source = db.get(RagSource, source_id)
        if source is not None:
            source.status = SourceStatus.ERROR
        db.commit()


def _summarize_for_indexing(content: str, *, max_chars: int = 500) -> str:
    """임베딩 검색 힌트용 짧은 비생성 요약을 만든다."""
    compact = " ".join(line.strip() for line in content.splitlines() if line.strip())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "..."


if __name__ == "__main__":
    main()
