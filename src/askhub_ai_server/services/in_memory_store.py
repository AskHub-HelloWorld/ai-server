from datetime import UTC, datetime
from uuid import uuid4

from askhub_ai_server.schemas.ingestion import (
    IngestionJobCreateRequest,
    IngestionJobResponse,
)
from askhub_ai_server.schemas.source import SourceCreateRequest, SourceResponse


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class InMemoryAskHubStore:
    def __init__(self) -> None:
        self._sources: dict[str, SourceResponse] = {}
        self._ingestion_jobs: dict[str, IngestionJobResponse] = {}

    def create_source(self, request: SourceCreateRequest) -> SourceResponse:
        source_id = str(uuid4())
        source = SourceResponse(
            source_id=source_id,
            source_type=request.source_type,
            name=request.name,
            team_id=request.team_id,
            status="registered",
            repo_url=request.repo_url,
            default_branch=request.default_branch,
            url=request.url,
            created_at=utc_now_iso(),
        )
        self._sources[source_id] = source
        return source

    def get_source(self, source_id: str) -> SourceResponse | None:
        return self._sources.get(source_id)

    def create_ingestion_job(
        self,
        request: IngestionJobCreateRequest,
    ) -> IngestionJobResponse | None:
        if request.source_id not in self._sources:
            return None

        now = utc_now_iso()
        job = IngestionJobResponse(
            job_id=str(uuid4()),
            source_id=request.source_id,
            mode=request.mode,
            status="queued",
            indexed_object_count=0,
            failure_reason=None,
            created_at=now,
            updated_at=now,
        )
        self._ingestion_jobs[job.job_id] = job
        return job

    def get_ingestion_job(self, job_id: str) -> IngestionJobResponse | None:
        return self._ingestion_jobs.get(job_id)


store = InMemoryAskHubStore()

