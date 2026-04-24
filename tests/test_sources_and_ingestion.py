import uuid

from conftest import auth_headers
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from askhub_ai_server.models.document import DocumentChunk, IngestionJob, RagSource
from askhub_ai_server.models.file import UserFile


def _create_user_file(
    db_session: Session,
    *,
    user_id: int = 1,
    team_id: int = 10,
    purpose: str = "rag_source",
) -> UserFile:
    user_file = UserFile(
        id=uuid.uuid4(),
        user_id=user_id,
        team_id=team_id,
        filename="guide.pdf",
        content_type="application/pdf",
        file_size=12,
        storage_path="s3://bucket/key",
        storage_provider="s3",
        storage_bucket="bucket",
        storage_key="key",
        purpose=purpose,
    )
    db_session.add(user_file)
    db_session.commit()
    return user_file


def test_create_source_and_ingestion_job(client: TestClient) -> None:
    source_response = client.post(
        "/v1/sources",
        headers=auth_headers("POST", "/v1/sources", user_id=1, team_id=10),
        json={
            "source_type": "repository",
            "name": "backend",
            "repo_url": "https://github.com/AskHub-HelloWorld/backend.git",
            "default_branch": "main",
        },
    )

    assert source_response.status_code == 201
    source = source_response.json()
    assert source["source_type"] == "repository"
    assert source["team_id"] == 10
    assert source["status"] == "registered"

    job_response = client.post(
        "/v1/ingestion-jobs",
        headers=auth_headers("POST", "/v1/ingestion-jobs", user_id=1, team_id=10),
        json={"source_id": source["source_id"], "mode": "full"},
    )

    assert job_response.status_code == 201
    job = job_response.json()
    assert job["source_id"] == source["source_id"]
    assert job["status"] == "queued"

    get_job_path = f"/v1/ingestion-jobs/{job['job_id']}"
    get_job_response = client.get(
        get_job_path,
        headers=auth_headers("GET", get_job_path, user_id=1, team_id=10),
    )

    assert get_job_response.status_code == 200
    assert get_job_response.json() == job


def test_create_ingestion_job_rejects_unknown_source(client: TestClient) -> None:
    response = client.post(
        "/v1/ingestion-jobs",
        headers=auth_headers("POST", "/v1/ingestion-jobs", user_id=1, team_id=10),
        json={"source_id": "00000000-0000-0000-0000-000000000000", "mode": "full"},
    )

    assert response.status_code == 404


def test_source_requires_team_context(client: TestClient) -> None:
    response = client.post(
        "/v1/sources",
        headers=auth_headers("POST", "/v1/sources", user_id=1, team_id=None),
        json={
            "source_type": "repository",
            "name": "backend",
            "repo_url": "https://github.com/AskHub-HelloWorld/backend.git",
        },
    )

    assert response.status_code == 400


def test_repository_source_requires_repo_url(client: TestClient) -> None:
    response = client.post(
        "/v1/sources",
        headers=auth_headers("POST", "/v1/sources", user_id=1, team_id=10),
        json={"source_type": "repository", "name": "backend"},
    )

    assert response.status_code == 422


def test_create_document_source_requires_owned_rag_file(
    client: TestClient,
    db_session: Session,
) -> None:
    user_file = _create_user_file(db_session)

    response = client.post(
        "/v1/sources",
        headers=auth_headers("POST", "/v1/sources", user_id=1, team_id=10),
        json={
            "source_type": "document",
            "name": "guide",
            "file_id": str(user_file.id),
        },
    )

    assert response.status_code == 201
    source = response.json()
    assert source["source_type"] == "document"
    assert source["file_id"] == str(user_file.id)
    assert source["chunk_count"] == 0


def test_create_document_source_rejects_other_users_file(
    client: TestClient,
    db_session: Session,
) -> None:
    user_file = _create_user_file(db_session, user_id=2, team_id=10)

    response = client.post(
        "/v1/sources",
        headers=auth_headers("POST", "/v1/sources", user_id=1, team_id=10),
        json={
            "source_type": "document",
            "name": "guide",
            "file_id": str(user_file.id),
        },
    )

    assert response.status_code == 404


def test_create_document_source_rejects_wrong_purpose_file(
    client: TestClient,
    db_session: Session,
) -> None:
    user_file = _create_user_file(db_session, purpose="chat_attachment")

    response = client.post(
        "/v1/sources",
        headers=auth_headers("POST", "/v1/sources", user_id=1, team_id=10),
        json={
            "source_type": "document",
            "name": "guide",
            "file_id": str(user_file.id),
        },
    )

    assert response.status_code == 404


def test_list_sources_includes_chunk_count(client: TestClient, db_session: Session) -> None:
    source = RagSource(
        source_type="repository",
        name="backend",
        team_id=10,
        status="ready",
        repo_url="https://github.com/test/repo",
    )
    db_session.add(source)
    db_session.flush()
    job = IngestionJob(source_id=source.id, mode="full", status="succeeded")
    db_session.add(job)
    db_session.flush()
    db_session.add(
        DocumentChunk(
            source_id=source.id,
            job_id=job.id,
            team_id=10,
            content="content",
            token_count=1,
            file_path="README.md",
            file_type="markdown",
            chunk_index=0,
            embedding=[0.0] * 1024,
        )
    )
    db_session.commit()

    response = client.get(
        "/v1/sources",
        headers=auth_headers("GET", "/v1/sources", user_id=1, team_id=10),
    )

    assert response.status_code == 200
    sources = response.json()["sources"]
    assert len(sources) == 1
    assert sources[0]["source_id"] == str(source.id)
    assert sources[0]["chunk_count"] == 1


def test_delete_source_cascades_chunks(client: TestClient, db_session: Session) -> None:
    source = RagSource(
        source_type="repository",
        name="backend",
        team_id=10,
        status="ready",
        repo_url="https://github.com/test/repo",
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
        content="content",
        token_count=1,
        file_path="README.md",
        file_type="markdown",
        chunk_index=0,
        embedding=[0.0] * 1024,
    )
    db_session.add(chunk)
    db_session.commit()

    source_id = source.id
    chunk_id = chunk.id
    delete_path = f"/v1/sources/{source_id}"
    response = client.delete(
        delete_path,
        headers=auth_headers("DELETE", delete_path, user_id=1, team_id=10),
    )

    assert response.status_code == 204
    db_session.expire_all()
    assert db_session.get(RagSource, source_id) is None
    assert db_session.get(DocumentChunk, chunk_id) is None
