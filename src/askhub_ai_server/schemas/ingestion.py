from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

IngestionMode = Literal["full", "incremental"]
IngestionJobStatus = Literal["queued", "running", "succeeded", "failed"]


class IngestionJobCreateRequest(BaseModel):
    source_id: UUID
    mode: IngestionMode = "full"


class IngestionJobResponse(BaseModel):
    job_id: UUID
    source_id: UUID
    mode: IngestionMode
    status: IngestionJobStatus
    indexed_object_count: int
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime
