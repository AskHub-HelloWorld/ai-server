"""인덱싱 작업 서비스 — ingestion job 생성 및 조회."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from askhub_ai_server.models.document import IngestionJob, RagSource
from askhub_ai_server.models.enums import JobStatus
from askhub_ai_server.services.exceptions import ServiceError


class IngestionJobService:
    """IngestionJob CRUD 오퍼레이션."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create_job(self, source_id: UUID, mode: str, team_id: int | None) -> IngestionJob:
        """소스에 대한 새 인덱싱 작업을 생성한다."""
        source = self._db.get(RagSource, source_id)
        if source is None or source.team_id != team_id:
            raise ServiceError(404, f"source not found: {source_id}")
        job = IngestionJob(
            source_id=source.id,
            mode=mode,
            status=JobStatus.QUEUED,
            indexed_object_count=0,
        )
        self._db.add(job)
        self._db.commit()
        self._db.refresh(job)
        return job

    def get_job(self, job_id: UUID, team_id: int | None) -> IngestionJob:
        """작업 ID로 인덱싱 작업을 조회한다."""
        job = self._db.get(IngestionJob, job_id)
        if job is None or job.source.team_id != team_id:
            raise ServiceError(404, f"ingestion job not found: {job_id}")
        return job

    @staticmethod
    def is_terminal(job: IngestionJob) -> bool:
        """작업이 종료 상태인지 확인한다."""
        return job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED)
