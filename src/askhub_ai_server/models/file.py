from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from askhub_ai_server.core.config import get_settings
from askhub_ai_server.core.database import Base
from askhub_ai_server.models.enums import FilePurpose

DB_SCHEMA = get_settings().db_schema

if TYPE_CHECKING:
    from askhub_ai_server.models.chat import ChatSession


class UserFile(Base):
    __tablename__ = "user_files"
    __table_args__ = (Index("ix_ai_user_files_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    team_id: Mapped[int | None] = mapped_column(BigInteger)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{DB_SCHEMA}.chat_sessions.id", ondelete="SET NULL"),
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    storage_bucket: Mapped[str | None] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FilePurpose.CHAT_ATTACHMENT,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    session: Mapped[ChatSession | None] = relationship()
