from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from askhub_ai_server.models.enums import FilePurpose


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
    purpose: FilePurpose
    file_kind: str | None = None
    file_kind_label: str | None = None
    created_at: datetime


class FileListResponse(BaseModel):
    """파일 목록 응답."""

    files: list[FileUploadResponse] = Field(default_factory=list)
    next_cursor: str | None = Field(
        default=None, description="다음 페이지 커서 (마지막 파일 ID)"
    )
    has_more: bool = Field(default=False, description="추가 페이지 존재 여부")
