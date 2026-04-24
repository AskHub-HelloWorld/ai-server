from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

SourceType = Literal["repository", "document"]


class SourceCreateRequest(BaseModel):
    source_type: SourceType
    name: str | None = Field(default=None, max_length=200)
    repo_url: str | None = None
    default_branch: str | None = None
    url: str | None = None
    file_id: UUID | None = None

    @model_validator(mode="after")
    def validate_source_location(self) -> "SourceCreateRequest":
        if self.source_type == "repository" and not self.repo_url:
            raise ValueError("repository source requires repo_url")
        if self.source_type == "document" and self.file_id is None:
            raise ValueError("document source requires file_id")
        return self


class SourceResponse(BaseModel):
    source_id: UUID
    source_type: SourceType
    name: str
    team_id: int
    status: Literal["registered", "indexing", "ready", "error"]
    status_label: str
    type_label: str
    repo_url: str | None = None
    default_branch: str | None = None
    url: str | None = None
    file_id: UUID | None = None
    summary: str | None = None
    chunk_count: int = 0
    created_at: datetime


class SourceListResponse(BaseModel):
    sources: list[SourceResponse] = Field(default_factory=list)
