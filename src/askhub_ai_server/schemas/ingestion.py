from typing import Literal

from pydantic import BaseModel

IngestionMode = Literal["full", "incremental"]
IngestionJobStatus = Literal["queued", "running", "succeeded", "failed"]


class IngestionJobCreateRequest(BaseModel):
    source_id: str
    mode: IngestionMode = "full"


class IngestionJobResponse(BaseModel):
    job_id: str
    source_id: str
    mode: IngestionMode
    status: IngestionJobStatus
    indexed_object_count: int
    failure_reason: str | None = None
    created_at: str
    updated_at: str

