import uuid

from sqlalchemy.orm import Session

from askhub_ai_server.core.config import get_settings
from askhub_ai_server.models.document import DocumentChunk, IngestionJob, RagSource
from askhub_ai_server.models.file import UserFile
from askhub_ai_server.worker import _process_document_source


class FakeStorage:
    def __init__(self) -> None:
        self.read_file_ids: list[uuid.UUID] = []

    def read_bytes(self, user_file: UserFile, max_bytes: int) -> bytes:
        self.read_file_ids.append(user_file.id)
        return b"first paragraph\n\nsecond paragraph"


class FakeEmbeddingService:
    def embed_text(self, text: str) -> list[float]:
        return [0.0] * 1024

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


def _create_file(db_session: Session, *, filename: str, team_id: int = 10) -> UserFile:
    file_id = uuid.uuid4()
    user_file = UserFile(
        id=file_id,
        user_id=1,
        team_id=team_id,
        filename=filename,
        content_type="text/plain",
        file_size=32,
        storage_path=f"s3://bucket/{file_id}/{filename}",
        storage_provider="s3",
        storage_bucket="bucket",
        storage_key=f"{file_id}/{filename}",
        purpose="rag_source",
    )
    db_session.add(user_file)
    db_session.flush()
    return user_file


def test_process_document_source_reads_only_linked_file(
    db_session: Session,
    monkeypatch,
) -> None:
    # 한국어 토크나이저가 search_text를 변환하므로 테스트에서는 비활성화
    monkeypatch.setattr(
        "askhub_ai_server.services.chunker._korean_tokenize_if_enabled",
        lambda text: text,
    )
    linked_file = _create_file(db_session, filename="linked.txt")
    other_file = _create_file(db_session, filename="other.txt")
    source = RagSource(
        source_type="document",
        name="linked",
        team_id=10,
        status="indexing",
        file_id=linked_file.id,
    )
    db_session.add(source)
    db_session.flush()
    job = IngestionJob(source_id=source.id, mode="full", status="running")
    db_session.add(job)
    db_session.flush()

    storage = FakeStorage()
    monkeypatch.setattr(
        "askhub_ai_server.worker.get_file_storage",
        lambda settings: storage,
    )

    count = _process_document_source(
        db_session,
        source,
        job,
        FakeEmbeddingService(),  # type: ignore[arg-type]
        get_settings(),
    )
    db_session.commit()

    assert count == 1
    assert storage.read_file_ids == [linked_file.id]
    assert other_file.id not in storage.read_file_ids
    chunk = db_session.query(DocumentChunk).one()
    assert chunk.file_path == "linked.txt"
    assert chunk.repo_url is None
    assert chunk.embedding_text is not None
    assert "source title: linked" in chunk.embedding_text
    assert chunk.search_text == chunk.embedding_text
    assert chunk.metadata_json["source_title"] == "linked"
