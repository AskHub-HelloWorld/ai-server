import os
from uuid import UUID

import boto3
import pytest
from conftest import auth_headers, live_bedrock_enabled
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import get_settings
from askhub_ai_server.models import Message, UserFile


def test_create_list_and_get_chat_session(client: TestClient) -> None:
    headers = auth_headers("POST", "/v1/chat/sessions", user_id=1, team_id=10)
    create_response = client.post("/v1/chat/sessions", headers=headers, json={})

    assert create_response.status_code == 201
    session = create_response.json()
    assert session["user_id"] == 1
    assert session["team_id"] == 10
    assert session["title"] is None

    list_response = client.get(
        "/v1/chat/sessions",
        headers=auth_headers("GET", "/v1/chat/sessions", user_id=1, team_id=10),
    )

    assert list_response.status_code == 200
    assert len(list_response.json()["sessions"]) == 1

    detail_path = f"/v1/chat/sessions/{session['session_id']}"
    detail_response = client.get(
        detail_path,
        headers=auth_headers("GET", detail_path, user_id=1, team_id=10),
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["session_id"] == session["session_id"]
    assert detail["messages"] == []


def test_chat_session_rejects_missing_service_auth(client: TestClient) -> None:
    response = client.post("/v1/chat/sessions", json={})

    assert response.status_code == 401


def test_chat_session_hides_other_users_session(client: TestClient) -> None:
    create_response = client.post(
        "/v1/chat/sessions",
        headers=auth_headers("POST", "/v1/chat/sessions", user_id=1, team_id=10),
        json={},
    )
    session_id = create_response.json()["session_id"]
    detail_path = f"/v1/chat/sessions/{session_id}"

    response = client.get(
        detail_path,
        headers=auth_headers("GET", detail_path, user_id=2, team_id=10),
    )

    assert response.status_code == 404


@pytest.mark.live_bedrock
@pytest.mark.skipif(not live_bedrock_enabled(), reason="requires real Bedrock access")
def test_create_session_message_with_live_bedrock(client: TestClient) -> None:
    create_response = client.post(
        "/v1/chat/sessions",
        headers=auth_headers("POST", "/v1/chat/sessions", user_id=1, team_id=10),
        json={},
    )
    session = create_response.json()
    message_path = f"/v1/chat/sessions/{session['session_id']}/messages"

    message_response = client.post(
        message_path,
        headers=auth_headers("POST", message_path, user_id=1, team_id=10),
        json={"message": "짧게 인사해줘.", "file_ids": []},
    )

    assert message_response.status_code == 200
    message_body = message_response.json()
    assert message_body["answerable"] is True
    assert message_body["answer"]

    detail_path = f"/v1/chat/sessions/{session['session_id']}"
    detail_response = client.get(
        detail_path,
        headers=auth_headers("GET", detail_path, user_id=1, team_id=10),
    )
    detail = detail_response.json()
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]


@pytest.mark.live_bedrock
@pytest.mark.skipif(not live_bedrock_enabled(), reason="requires real Bedrock access")
def test_create_session_message_with_live_bedrock_image(client: TestClient) -> None:
    image_path = os.getenv("LIVE_BEDROCK_IMAGE_PATH")
    if not image_path:
        pytest.skip("requires LIVE_BEDROCK_IMAGE_PATH")

    create_response = client.post(
        "/v1/chat/sessions",
        headers=auth_headers("POST", "/v1/chat/sessions", user_id=1, team_id=10),
        json={},
    )
    session = create_response.json()

    upload_path = "/v1/files/upload"
    with open(image_path, "rb") as image:
        upload_response = client.post(
            upload_path,
            headers=auth_headers("POST", upload_path, user_id=1, team_id=10),
            files={"file": ("image.png", image, "image/png")},
            data={
                "purpose": "chat_attachment",
                "session_id": session["session_id"],
            },
        )

    assert upload_response.status_code == 201
    file_id = upload_response.json()["id"]
    message_path = f"/v1/chat/sessions/{session['session_id']}/messages"

    message_response = client.post(
        message_path,
        headers=auth_headers("POST", message_path, user_id=1, team_id=10),
        json={
            "message": "이미지에 적힌 문구를 읽고 핵심 문구를 그대로 답해줘.",
            "file_ids": [file_id],
        },
    )

    assert message_response.status_code == 200
    answer = message_response.json()["answer"]
    assert answer
    assert any(keyword in answer for keyword in ["AWS", "비밀번호", "POSTGRES", "SERVICE_AUTH"])


@pytest.mark.live_bedrock
@pytest.mark.skipif(not live_bedrock_enabled(), reason="requires real Bedrock access")
def test_create_session_message_with_live_bedrock_image_s3(
    client: TestClient,
    db_session: Session,
) -> None:
    image_path = os.getenv("LIVE_BEDROCK_IMAGE_PATH")
    if not image_path:
        pytest.skip("requires LIVE_BEDROCK_IMAGE_PATH")

    settings = get_settings()
    assert settings.file_storage_backend == "s3"
    assert settings.s3_bucket

    create_response = client.post(
        "/v1/chat/sessions",
        headers=auth_headers("POST", "/v1/chat/sessions", user_id=1010, team_id=2020),
        json={},
    )
    session = create_response.json()

    storage_key: str | None = None
    s3_client = boto3.client("s3", region_name=settings.s3_region)
    try:
        upload_path = "/v1/files/upload"
        with open(image_path, "rb") as image:
            upload_response = client.post(
                upload_path,
                headers=auth_headers("POST", upload_path, user_id=1010, team_id=2020),
                files={"file": ("image.png", image, "image/png")},
                data={
                    "purpose": "chat_attachment",
                    "session_id": session["session_id"],
                },
            )

        assert upload_response.status_code == 201
        file_id = upload_response.json()["id"]
        user_file = db_session.get(UserFile, file_id)
        assert user_file is not None
        assert user_file.storage_provider == "s3"
        assert user_file.storage_bucket == settings.s3_bucket
        assert user_file.storage_key
        assert user_file.storage_path == f"s3://{settings.s3_bucket}/{user_file.storage_key}"
        storage_key = user_file.storage_key

        head = s3_client.head_object(Bucket=settings.s3_bucket, Key=storage_key)
        assert head["ContentLength"] == user_file.file_size

        message_path = f"/v1/chat/sessions/{session['session_id']}/messages"
        message_response = client.post(
            message_path,
            headers=auth_headers("POST", message_path, user_id=1010, team_id=2020),
            json={
                "message": "해당 이미지의 글씨가 뭐라고 써져있어?",
                "file_ids": [file_id],
            },
        )

        assert message_response.status_code == 200
        answer = message_response.json()["answer"]
        assert answer
        assert any(keyword in answer for keyword in ["AWS", "비밀번호", "POSTGRES", "SERVICE_AUTH"])

        messages = db_session.scalars(
            select(Message)
            .where(Message.session_id == UUID(session["session_id"]))
            .order_by(Message.created_at.asc(), Message.id.asc())
        ).all()
        assert [message.role for message in messages] == ["user", "assistant"]
    finally:
        if storage_key:
            s3_client.delete_object(Bucket=settings.s3_bucket, Key=storage_key)


@pytest.mark.live_bedrock
@pytest.mark.skipif(not live_bedrock_enabled(), reason="requires real Bedrock access")
def test_stream_session_message_with_live_bedrock(client: TestClient) -> None:
    create_response = client.post(
        "/v1/chat/sessions",
        headers=auth_headers("POST", "/v1/chat/sessions", user_id=1, team_id=10),
        json={},
    )
    session = create_response.json()
    stream_path = f"/v1/chat/sessions/{session['session_id']}/messages/stream"

    with client.stream(
        "POST",
        stream_path,
        headers=auth_headers("POST", stream_path, user_id=1, team_id=10),
        json={"message": "짧게 인사해줘.", "file_ids": []},
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert "event: metadata" in body
    assert "event: token" in body
    assert "event: done" in body
