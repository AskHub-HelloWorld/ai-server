from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from askhub_ai_server.core.config import get_settings
from askhub_ai_server.core.database import Base
from askhub_ai_server.models.enums import JobStatus, SourceStatus

DB_SCHEMA = get_settings().db_schema


class RagSource(Base):
    __tablename__ = "rag_sources"
    __table_args__ = (Index("ix_ai_rag_sources_team_id", "team_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    team_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SourceStatus.REGISTERED)
    repo_url: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{DB_SCHEMA}.user_files.id", ondelete="SET NULL"),
    )
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("ix_ai_ingestion_jobs_source_id", "source_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{DB_SCHEMA}.rag_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=JobStatus.QUEUED)
    indexed_object_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    source: Mapped[RagSource] = relationship(back_populates="ingestion_jobs")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class DocumentChunk(Base):
    """RAG용 문서/코드 청크 — pgvector 임베딩 포함."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_ai_document_chunks_source_id", "source_id"),
        Index("ix_ai_document_chunks_job_id", "job_id"),
        Index("ix_ai_document_chunks_team_id", "team_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{DB_SCHEMA}.rag_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{DB_SCHEMA}.ingestion_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    team_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_text: Mapped[str | None] = mapped_column(Text)
    search_text: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Source location metadata (for citations)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(50))
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Git metadata (for repository sources)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    repo_url: Mapped[str | None] = mapped_column(Text)

    # Vector embedding — Titan Embed v2 outputs 1024 dimensions
    embedding: Mapped[Any] = mapped_column(Vector(1024), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    source: Mapped[RagSource] = relationship(back_populates="chunks")
    job: Mapped[IngestionJob] = relationship(back_populates="chunks")
