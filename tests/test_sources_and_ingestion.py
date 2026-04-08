from fastapi.testclient import TestClient

from askhub_ai_server.main import create_app


def test_create_source_and_ingestion_job() -> None:
    client = TestClient(create_app())

    source_response = client.post(
        "/v1/sources",
        json={
            "source_type": "repository",
            "name": "backend",
            "team_id": 10,
            "repo_url": "https://github.com/AskHub-HelloWorld/backend.git",
            "default_branch": "main",
        },
    )

    assert source_response.status_code == 201
    source = source_response.json()
    assert source["source_type"] == "repository"
    assert source["status"] == "registered"

    job_response = client.post(
        "/v1/ingestion-jobs",
        json={"source_id": source["source_id"], "mode": "full"},
    )

    assert job_response.status_code == 201
    job = job_response.json()
    assert job["source_id"] == source["source_id"]
    assert job["status"] == "queued"

    get_job_response = client.get(f"/v1/ingestion-jobs/{job['job_id']}")

    assert get_job_response.status_code == 200
    assert get_job_response.json() == job


def test_create_ingestion_job_rejects_unknown_source() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/ingestion-jobs",
        json={"source_id": "missing-source", "mode": "full"},
    )

    assert response.status_code == 404


def test_repository_source_requires_repo_url() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/sources",
        json={"source_type": "repository", "name": "backend", "team_id": 10},
    )

    assert response.status_code == 422

