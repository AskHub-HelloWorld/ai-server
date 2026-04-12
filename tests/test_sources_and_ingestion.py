from conftest import auth_headers
from fastapi.testclient import TestClient


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
