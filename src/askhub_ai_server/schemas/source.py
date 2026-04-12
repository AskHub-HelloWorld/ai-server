from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

SourceType = Literal["repository", "document"]


class SourceCreateRequest(BaseModel):
    source_type: SourceType
    name: str = Field(min_length=1, max_length=200)
    repo_url: str | None = None
    default_branch: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def validate_source_location(self) -> "SourceCreateRequest":
        if self.source_type == "repository" and not self.repo_url:
            raise ValueError("repository source requires repo_url")
        if self.source_type == "document" and not self.url:
            raise ValueError("document source requires url")
        return self


class SourceResponse(BaseModel):
    source_id: UUID
    source_type: SourceType
    name: str
    team_id: int
    status: Literal["registered"]
    repo_url: str | None = None
    default_branch: str | None = None
    url: str | None = None
    created_at: datetime
