"""document_chunks 테이블 및 DocumentChunk 모델 테스트."""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import get_settings
from askhub_ai_server.models.document import DocumentChunk, IngestionJob, RagSource
from askhub_ai_server.models.file import UserFile


def test_document_chunks_table_exists(db_session: Session) -> None:
    """마이그레이션 후 document_chunks 테이블이 존재하는지 확인."""
    settings = get_settings()
    result = db_session.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = :schema AND table_name = 'document_chunks'"
            ")"
        ),
        {"schema": settings.db_schema},
    )
    assert result.scalar() is True


def test_document_chunks_vector_column_exists(db_session: Session) -> None:
    """embedding 컬럼(vector 타입)이 존재하는지 확인."""
    settings = get_settings()
    result = db_session.execute(
        text(
            "SELECT column_name, udt_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = 'document_chunks' "
            "AND column_name = 'embedding'"
        ),
        {"schema": settings.db_schema},
    )
    row = result.fetchone()
    assert row is not None
    assert row[1] == "vector"


def test_document_chunks_search_metadata_columns_exist(db_session: Session) -> None:
    """검색용 contextual text와 metadata 컬럼이 존재하는지 확인."""
    settings = get_settings()
    result = db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = 'document_chunks' "
            "AND column_name IN ('embedding_text', 'search_text', 'metadata_json')"
        ),
        {"schema": settings.db_schema},
    )
    columns = {row[0] for row in result.fetchall()}
    assert columns == {"embedding_text", "search_text", "metadata_json"}


def test_rag_sources_file_id_column_exists(db_session: Session) -> None:
    settings = get_settings()
    result = db_session.execute(
        text(
            "SELECT column_name, udt_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = 'rag_sources' "
            "AND column_name = 'file_id'"
        ),
        {"schema": settings.db_schema},
    )
    row = result.fetchone()
    assert row is not None
    assert row[1] == "uuid"


def test_insert_and_query_document_chunk(db_session: Session) -> None:
    """DocumentChunk 모델로 insert + select가 정상 동작하는지 확인."""
    # 먼저 source, job 생성
    source = RagSource(
        source_type="repository",
        name="test-repo",
        team_id=10,
        status="registered",
        repo_url="https://github.com/test/repo",
    )
    db_session.add(source)
    db_session.flush()

    job = IngestionJob(
        source_id=source.id,
        mode="full",
        status="running",
    )
    db_session.add(job)
    db_session.flush()

    # 1024차원 벡터 (모두 0으로 채움)
    dummy_embedding = [0.0] * 1024

    chunk = DocumentChunk(
        source_id=source.id,
        job_id=job.id,
        team_id=10,
        content="def hello():\n    print('hi')",
        embedding_text="file path: src/main.py\nsymbol name: hello\ncontent:\ndef hello():",
        search_text="src/main.py hello def hello",
        metadata_json={"symbol_name": "hello", "symbol_type": "function"},
        token_count=5,
        file_path="src/main.py",
        file_type="python",
        line_start=1,
        line_end=2,
        chunk_index=0,
        commit_sha="abc1234def5678",
        repo_url="https://github.com/test/repo",
        embedding=dummy_embedding,
    )
    db_session.add(chunk)
    db_session.commit()
    db_session.refresh(chunk)

    assert chunk.id is not None
    assert chunk.content == "def hello():\n    print('hi')"
    assert chunk.file_path == "src/main.py"
    assert chunk.line_start == 1
    assert chunk.line_end == 2
    assert chunk.commit_sha == "abc1234def5678"
    assert chunk.metadata_json["symbol_name"] == "hello"


def test_rag_source_allows_new_statuses(db_session: Session) -> None:
    """rag_sources 상태 constraint가 indexing/ready/error를 허용하는지 확인."""
    for status in ("registered", "indexing", "ready", "error"):
        source = RagSource(
            source_type="document",
            name=f"test-{status}",
            team_id=10,
            status=status,
        )
        db_session.add(source)
    db_session.commit()

    sources = db_session.query(RagSource).filter(RagSource.team_id == 10).all()
    statuses = {s.status for s in sources}
    assert statuses == {"registered", "indexing", "ready", "error"}


def test_rag_source_can_reference_user_file(db_session: Session) -> None:
    user_file = UserFile(
        id=uuid.uuid4(),
        user_id=1,
        team_id=10,
        filename="guide.pdf",
        content_type="application/pdf",
        file_size=12,
        storage_path="s3://bucket/key",
        storage_provider="s3",
        storage_bucket="bucket",
        storage_key="key",
        purpose="rag_source",
    )
    db_session.add(user_file)
    db_session.flush()

    source = RagSource(
        source_type="document",
        name="guide",
        team_id=10,
        status="registered",
        file_id=user_file.id,
    )
    db_session.add(source)
    db_session.commit()

    assert source.file_id == user_file.id


def test_cascade_delete_source_removes_chunks(db_session: Session) -> None:
    """RagSource 삭제 시 관련 DocumentChunk가 CASCADE 삭제되는지 확인."""
    source = RagSource(
        source_type="repository",
        name="cascade-test",
        team_id=10,
        status="ready",
        repo_url="https://github.com/test/cascade",
    )
    db_session.add(source)
    db_session.flush()

    job = IngestionJob(source_id=source.id, mode="full", status="succeeded")
    db_session.add(job)
    db_session.flush()

    chunk = DocumentChunk(
        source_id=source.id,
        job_id=job.id,
        team_id=10,
        content="test content",
        token_count=2,
        file_path="test.py",
        file_type="python",
        chunk_index=0,
        embedding=[0.0] * 1024,
    )
    db_session.add(chunk)
    db_session.commit()

    chunk_id = chunk.id
    db_session.delete(source)
    db_session.commit()

    assert db_session.get(DocumentChunk, chunk_id) is None
