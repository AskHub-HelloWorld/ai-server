import boto3
from conftest import auth_headers
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import get_settings
from askhub_ai_server.models import UserFile


def test_upload_list_and_get_file_metadata(client: TestClient, db_session: Session) -> None:
    settings = get_settings()
    s3_client = boto3.client("s3", region_name=settings.s3_region)
    storage_key: str | None = None

    try:
        response = client.post(
            "/v1/files/upload",
            headers=auth_headers("POST", "/v1/files/upload", user_id=1, team_id=10),
            files={"file": ("error.log", b"line one\nline two\n", "text/plain")},
            data={"purpose": "chat_attachment"},
        )

        assert response.status_code == 201
        uploaded = response.json()
        assert uploaded["filename"] == "error.log"
        assert uploaded["user_id"] == 1
        assert uploaded["team_id"] == 10
        assert "storage_path" not in uploaded

        user_file = db_session.get(UserFile, uploaded["id"])
        assert user_file is not None
        assert user_file.storage_provider == "s3"
        assert user_file.storage_bucket == settings.s3_bucket
        assert user_file.storage_key is not None
        storage_key = user_file.storage_key

        list_response = client.get(
            "/v1/files",
            headers=auth_headers("GET", "/v1/files", user_id=1, team_id=10),
        )
        assert list_response.status_code == 200
        assert len(list_response.json()["files"]) == 1

        get_path = f"/v1/files/{uploaded['id']}"
        get_response = client.get(
            get_path,
            headers=auth_headers("GET", get_path, user_id=1, team_id=10),
        )
        assert get_response.status_code == 200
        assert get_response.json()["id"] == uploaded["id"]
    finally:
        if storage_key:
            s3_client.delete_object(Bucket=settings.s3_bucket, Key=storage_key)


def test_file_metadata_hides_other_users_file(client: TestClient, db_session: Session) -> None:
    settings = get_settings()
    s3_client = boto3.client("s3", region_name=settings.s3_region)
    storage_key: str | None = None

    try:
        response = client.post(
            "/v1/files/upload",
            headers=auth_headers("POST", "/v1/files/upload", user_id=1, team_id=10),
            files={"file": ("error.log", b"line one\n", "text/plain")},
            data={"purpose": "chat_attachment"},
        )
        uploaded = response.json()
        user_file = db_session.get(UserFile, uploaded["id"])
        if user_file:
            storage_key = user_file.storage_key

        get_path = f"/v1/files/{uploaded['id']}"
        get_response = client.get(
            get_path,
            headers=auth_headers("GET", get_path, user_id=2, team_id=10),
        )

        assert get_response.status_code == 404
    finally:
        if storage_key:
            s3_client.delete_object(Bucket=settings.s3_bucket, Key=storage_key)


def test_upload_accepts_png_content_type(client: TestClient, db_session: Session) -> None:
    settings = get_settings()
    s3_client = boto3.client("s3", region_name=settings.s3_region)
    storage_key: str | None = None

    try:
        response = client.post(
            "/v1/files/upload",
            headers=auth_headers("POST", "/v1/files/upload", user_id=1, team_id=10),
            files={"file": ("image.png", b"not really an image", "image/png")},
            data={"purpose": "chat_attachment"},
        )

        assert response.status_code == 201
        assert response.json()["content_type"] == "image/png"
        user_file = db_session.get(UserFile, response.json()["id"])
        if user_file:
            storage_key = user_file.storage_key
    finally:
        if storage_key:
            s3_client.delete_object(Bucket=settings.s3_bucket, Key=storage_key)


def test_upload_accepts_pdf_content_type(client: TestClient, db_session: Session) -> None:
    settings = get_settings()
    s3_client = boto3.client("s3", region_name=settings.s3_region)
    storage_key: str | None = None

    try:
        response = client.post(
            "/v1/files/upload",
            headers=auth_headers("POST", "/v1/files/upload", user_id=1, team_id=10),
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"purpose": "chat_attachment"},
        )

        assert response.status_code == 201
        assert response.json()["content_type"] == "application/pdf"
        user_file = db_session.get(UserFile, response.json()["id"])
        if user_file:
            storage_key = user_file.storage_key
    finally:
        if storage_key:
            s3_client.delete_object(Bucket=settings.s3_bucket, Key=storage_key)


def test_upload_accepts_docx_content_type(client: TestClient, db_session: Session) -> None:
    settings = get_settings()
    s3_client = boto3.client("s3", region_name=settings.s3_region)
    storage_key: str | None = None

    try:
        ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        response = client.post(
            "/v1/files/upload",
            headers=auth_headers("POST", "/v1/files/upload", user_id=1, team_id=10),
            files={"file": ("report.docx", b"PK\x03\x04 fake docx", ct)},
            data={"purpose": "chat_attachment"},
        )

        assert response.status_code == 201
        assert response.json()["content_type"] == ct
        user_file = db_session.get(UserFile, response.json()["id"])
        if user_file:
            storage_key = user_file.storage_key
    finally:
        if storage_key:
            s3_client.delete_object(Bucket=settings.s3_bucket, Key=storage_key)


def test_upload_accepts_any_content_type(client: TestClient, db_session: Session) -> None:
    settings = get_settings()
    s3_client = boto3.client("s3", region_name=settings.s3_region)
    storage_key: str | None = None

    try:
        response = client.post(
            "/v1/files/upload",
            headers=auth_headers("POST", "/v1/files/upload", user_id=1, team_id=10),
            files={"file": ("archive.zip", b"PK\x03\x04 fake zip", "application/zip")},
            data={"purpose": "chat_attachment"},
        )

        assert response.status_code == 201
        assert response.json()["content_type"] == "application/zip"
        user_file = db_session.get(UserFile, response.json()["id"])
        if user_file:
            storage_key = user_file.storage_key
    finally:
        if storage_key:
            s3_client.delete_object(Bucket=settings.s3_bucket, Key=storage_key)
