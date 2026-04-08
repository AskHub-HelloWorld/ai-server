from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FileUploadResponse(BaseModel):
    """파일 업로드 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: int
    team_id: int | None = None
    session_id: UUID | None = None
    filename: str
    content_type: str | None = None
    file_size: int | None = None
    storage_path: str
    purpose: Literal["chat_attachment", "rag_source"]
    created_at: datetime


class FileListResponse(BaseModel):
    """파일 목록 응답."""

    files: list[FileUploadResponse] = Field(default_factory=list)
